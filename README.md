# Bursty Traffic Generator (VR/XR)

This repository provides a Python implementation of a bursty traffic generator based on the ns-3 VR/XR application from the original authors:
https://github.com/signetlabdei/ns-3-vr-app

The generator replays recorded traces from real-world scenarios and can also synthesize unlimited traces using the authors' models.

## What this repo is

Akhila Rao ported the ns-3 C++ implementation to Python (with minimal changes to behavior).

## Quick start

Open and read these files to learn how to set up and run the receiver and sender:

- `vr_burst_receiver.sh`
- `vr_burst_sender.sh`

To explore available options:

```bash
./vr_burst_receiver.py --help
./vr_burst_sender.py --help
```

You can save your desired settings in the `.sh` files and run:

```bash
bash vr_burst_receiver.sh
bash vr_burst_sender.sh
```
