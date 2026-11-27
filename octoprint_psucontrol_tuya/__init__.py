# coding=utf-8
from __future__ import absolute_import

import threading
import time

import octoprint.plugin


class PSUControlTuya(octoprint.plugin.StartupPlugin,
                     octoprint.plugin.SettingsPlugin,
                     octoprint.plugin.TemplatePlugin):

    def __init__(self):
        self._lock = threading.Lock()
        self._tinytuya = None
        self._last_state = False
        self._last_state_known = False
        self._fail_streak = 0          # consecutive failed polls (after retries)
        self._fail_since = None        # time.time() of first failure in streak

    # ---- Settings -------------------------------------------------------

    def get_settings_defaults(self):
        return dict(
            device_id="",
            address="Auto",      # IP address, or "Auto" to scan the LAN (slower)
            local_key="",
            version="3.4",       # 3.1, 3.3, 3.4 or 3.5
            switch_dps=1,        # DPS index of the on/off switch (usually 1)
            timeout=5,           # socket timeout in seconds
            retries=2,
        )

    def get_settings_version(self):
        return 1

    def get_template_configs(self):
        return [dict(type="settings", custom_bindings=False)]

    # ---- Startup / registration with PSU Control ------------------------

    def _describe_config(self):
        s = self._settings
        dev_id = s.get(["device_id"]) or ""
        masked = (dev_id[:4] + "..." + dev_id[-4:]) if len(dev_id) > 8 else (dev_id or "<unset>")
        return "device_id=%s address=%s version=%s dps=%s timeout=%ss key_set=%s" % (
            masked, s.get(["address"]) or "Auto", s.get(["version"]),
            s.get(["switch_dps"]), s.get(["timeout"]), bool(s.get(["local_key"])))

    def on_settings_save(self, data):
        octoprint.plugin.SettingsPlugin.on_settings_save(self, data)
        self._logger.info("Settings saved: %s", self._describe_config())

    def on_after_startup(self):
        try:
            import tinytuya
            self._logger.info("tinytuya %s", getattr(tinytuya, "__version__", "unknown"))
        except Exception:
            self._logger.error("tinytuya is not importable - plugin cannot work", exc_info=True)
        self._logger.info("Config: %s", self._describe_config())
        # Must run after PSU Control has finished its own startup, otherwise
        # its helpers are not available yet and we never get registered.
        helpers = self._plugin_manager.get_helpers("psucontrol", "register_plugin")
        if not helpers or "register_plugin" not in helpers:
            self._logger.warning(
                "PSU Control not found or too old to support sub-plugins; not registering.")
            return
        self._logger.info("Registering with PSU Control")
        helpers["register_plugin"](self)

    # ---- tinytuya helpers -----------------------------------------------

    def _device(self):
        if self._tinytuya is None:
            import tinytuya
            self._tinytuya = tinytuya

        s = self._settings
        dev_id = s.get(["device_id"])
        key = s.get(["local_key"])
        if not dev_id or not key:
            raise ValueError("Tuya device ID and local key must be configured")

        d = self._tinytuya.OutletDevice(dev_id, s.get(["address"]) or "Auto", key)
        d.set_version(float(s.get(["version"]) or 3.4))
        d.set_socketTimeout(float(s.get(["timeout"]) or 5))
        return d

    def _switch(self):
        return int(self._settings.get_int(["switch_dps"]) or 1)

    def _set(self, on):
        label = "on" if on else "off"
        t0 = time.time()
        try:
            with self._lock:
                d = self._device()
                result = d.set_status(bool(on), self._switch())
            ms = int((time.time() - t0) * 1000)
            if isinstance(result, dict) and (result.get("Error") or result.get("Err")):
                self._logger.error("Switch %s FAILED after %dms: %s", label, ms, result)
                return False
            self._logger.info("Switch %s OK in %dms, response: %s", label, ms, result)
            self._note_state(bool(on), source="command")
            return True
        except Exception:
            self._logger.exception("Switch %s raised after %dms", label, int((time.time() - t0) * 1000))
            return False

    def _note_state(self, state, source):
        """Record state and log transitions."""
        if self._last_state_known and state != self._last_state:
            self._logger.info("PSU state changed: %s -> %s (via %s)",
                              "on" if self._last_state else "off", "on" if state else "off", source)
        self._last_state = state
        self._last_state_known = True

    # ---- PSU Control sub-plugin API -------------------------------------

    def turn_psu_on(self):
        self._logger.info("Switching PSU on")
        self._set(True)

    def turn_psu_off(self):
        self._logger.info("Switching PSU off")
        self._set(False)

    def get_psu_state(self):
        """Return the plug's on/off state.

        PSU Control polls this regularly and treats False as "PSU is off",
        which disconnects the printer. A flaky LAN poll must therefore never
        be reported as "off": on any failure we return the last known state.
        """
        last_problem = None
        t0 = time.time()
        for attempt in range(1, 4):
            try:
                with self._lock:
                    status = self._device().status()
                if isinstance(status, dict) and isinstance(status.get("dps"), dict):
                    dps = status["dps"]
                    value = dps.get(str(self._switch()))
                    if value is None:
                        value = dps.get(self._switch())
                    if value is not None:
                        ms = int((time.time() - t0) * 1000)
                        if self._fail_streak:
                            self._logger.info(
                                "Plug reachable again after %d failed poll(s) over %ds (attempt %d, %dms)",
                                self._fail_streak, int(time.time() - self._fail_since), attempt, ms)
                        self._fail_streak = 0
                        self._fail_since = None
                        self._logger.debug("Poll OK in %dms (attempt %d): dps=%s", ms, attempt, dps)
                        self._note_state(bool(value), source="poll")
                        return self._last_state
                last_problem = "unexpected response: %r" % (status,)
            except Exception as e:
                last_problem = "%s: %s" % (type(e).__name__, e)
            self._logger.debug("Poll attempt %d/3 failed: %s", attempt, last_problem)
            time.sleep(0.5)

        # All attempts failed: keep last known state, log with rate limiting
        # (first failure, then every 10th) so a dead plug doesn't flood the log.
        if self._fail_streak == 0:
            self._fail_since = time.time()
        self._fail_streak += 1
        if self._fail_streak == 1 or self._fail_streak % 10 == 0:
            self._logger.warning(
                "Plug did not answer (failed poll #%d in a row, %ds so far, last error: %s). "
                "Reporting last known state: %s",
                self._fail_streak, int(time.time() - self._fail_since), last_problem,
                ("on" if self._last_state else "off") if self._last_state_known else "off (never read)")
        return self._last_state

    # ---- Update info ----------------------------------------------------

    def get_update_information(self):
        return dict(
            psucontrol_tuya=dict(
                displayName="PSU Control - Tuya",
                displayVersion=self._plugin_version,
                type="github_release",
                user="JZRod",
                repo="PSUControl-Tuya-Smartplug",
                current=self._plugin_version,
                pip="https://github.com/JZRod/PSUControl-Tuya-Smartplug/archive/{target_version}.zip",
            )
        )


__plugin_name__ = "PSU Control - Tuya"
__plugin_pythoncompat__ = ">=3.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = PSUControlTuya()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config":
            __plugin_implementation__.get_update_information
    }
