# QR tags and kiosk display

Optional. A tag on each pot opens the **quick page** of the plant that currently stands in that spot: photo, watering, note, tasks. In the app, a tag of an empty spot opens the form to plant one; on the LAN port it shows a hint. Tags stay valid when plants change.

## 1. Switch the port on

The quick pages are served on a separate LAN port **without Home Assistant login**, under a long random secret. Only quick pages and the kiosk display are reachable there, everything else answers 404. Do not forward this port to the internet.

1. Add-on **Network** section: set the host port for `8100/tcp` (same number as the option `public_port`, default 8100).
2. Optionally set `ha_url` (for example `http://homeassistant.local:8123`) so the links use the right host name.
3. Open **Master data → QR labels** in Growmi. It shows one code per spot with its address and can be printed on paper as it is.

The secret is stored in the Growmi database and survives updates and restores. If you delete the add-on **without** a backup, the tags need reprinting.

## 2. Print 3D tags (optional)

```sh
pip install segno
echo '{"1": "http://homeassistant.local:8100/s/<secret>/platz/1", "2": "..."}' > urls.json
python tools/make_qr_stl.py urls.json stl
```

Per spot you get `spot-N-tag.stl` (one body), or `spot-N-base.stl` plus `spot-N-qr.stl` for a two-colour printer. Plate 2.0 mm, code and number raised 0.8 mm, one module 1.2 mm. Print flat with a 0.4 mm nozzle and 0.2 mm layers. For one colour, insert a colour change at 2.0 mm height. Use high contrast (light plate, dark code) and test the scan before you hang the tag. Do not scale it down: below 1 mm per module the code scans badly.

## 3. Kiosk display

`http://<host>:8100/s/<secret>/kiosk` shows phase, climate, devices, alarms and due tasks. It suits an old phone at the tent with a browser in fullscreen. Keep its battery healthy with the *Kiosk phone charge guard* blueprint.
