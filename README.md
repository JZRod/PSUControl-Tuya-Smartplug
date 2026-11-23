# OctoPrint-PSUControl-Tuya

A sub-plugin for [OctoPrint-PSUControl](https://github.com/kantlivelong/OctoPrint-PSUControl)
that switches your printer's PSU through a Tuya smart plug, using
[tinytuya](https://github.com/jasonacox/tinytuya) for **local LAN control** (no cloud round-trip at print time).

## Install

Requires OctoPrint-PSUControl >= 1.0.0 (sub-plugin support).

```
pip install https://github.com/JZRod/PSUControl-Tuya-Smartplug/archive/main.zip
```

(Or install from a local folder: `pip install .` using OctoPrint's virtualenv.)

## Get your device ID and local key

1. Pair the plug with the Tuya / Smart Life app.
2. Create a project at [iot.tuya.com](https://iot.tuya.com) and link your app account.
3. Run `python -m tinytuya wizard` and follow the prompts. It writes `devices.json`
   containing each device's `id`, `key` and, after `python -m tinytuya scan`, its IP.
4. Reserve a static IP for the plug in your router.

## Configure

1. Settings -> PSU Control -> set **Switching** and **Sensing** to `PSU Control - Tuya`.
2. Settings -> PSU Control - Tuya -> enter Device ID, IP, Local key and protocol version.
3. Leave *Switch DPS* at `1` unless it is a multi-outlet device.

## Notes

- Protocol 3.4/3.5 devices need a recent tinytuya (>= 1.13).
- If "Auto" IP is used, each call scans the network; set a fixed IP instead.
- Sensing reads the plug's own switch state, so it reports correctly even when the plug is toggled from the app.
- Tuya plugs often keep the relay state after a power cut; set the plug's "power-on behavior" to Off in the Tuya app if you want it to default off.

## License

AGPLv3
