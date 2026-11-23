# coding=utf-8
from __future__ import absolute_import

import threading

import octoprint.plugin


class PSUControlTuya(octoprint.plugin.StartupPlugin,
                     octoprint.plugin.SettingsPlugin,
                     octoprint.plugin.TemplatePlugin):

    def __init__(self):
        self._lock = threading.Lock()
        self._tinytuya = None

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

    def on_after_startup(self):
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
        try:
            with self._lock:
                d = self._device()
                result = d.set_status(bool(on), self._switch())
            self._logger.info("Tuya set_status result: %s", result)
            if isinstance(result, dict) and result.get("Error"):
                self._logger.error("Tuya error: %s", result)
                return False
            return True
        except Exception:
            self._logger.exception("Failed to switch Tuya plug %s", "on" if on else "off")
            return False

    # ---- PSU Control sub-plugin API -------------------------------------

    def turn_psu_on(self):
        self._logger.info("Switching PSU on")
        self._set(True)

    def turn_psu_off(self):
        self._logger.info("Switching PSU off")
        self._set(False)

    def get_psu_state(self):
        try:
            with self._lock:
                status = self._device().status()
            if not isinstance(status, dict) or "dps" not in status:
                self._logger.error("Unexpected Tuya status response: %s", status)
                return False
            dps = status["dps"]
            value = dps.get(str(self._switch()))
            if value is None:
                value = dps.get(self._switch())
            return bool(value)
        except Exception:
            self._logger.exception("Failed to read Tuya plug state")
            return False

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
