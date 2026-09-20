# Tenda MW6 Home Assistant

Home Assistant integration and reverse-engineering notes for Tenda Nova MW6.

## Scope

The integration communicates only with the local MW6 protocol and does not depend
on Tenda cloud services. It exposes discovered clients, online state, Wi-Fi signal,
per-client upload/download rates, and locally accumulated traffic counters.

## Installation

Install the repository through HACS as an integration, restart Home Assistant,
then add **Tenda MW6** through *Settings → Devices & services*.

The bundled Lovelace card is available as `custom:tenda-mw6-card`. It discovers
all integration devices automatically and supports sorting by device name, IP,
download, and upload.

## Local diagnostics

The tools under `tools/` are designed for read-only local investigation.
Capture files and authentication material are intentionally ignored by Git.
Use placeholders in all examples and documentation; never commit a real device
name, MAC address, serial number, private IP address, or local user path.

## Safety

Unknown router commands are intentionally not sent. See [SECURITY.md](SECURITY.md)
for the repository privacy policy.
