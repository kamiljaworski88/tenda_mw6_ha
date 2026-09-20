# Security and privacy policy

This repository must contain only reusable integration code, synthetic test data,
and documentation derived from public firmware analysis.

Do not commit router captures, login material, Home Assistant `.storage` data,
certificates, local configuration, device names, MAC addresses, serial numbers,
private IP addresses, or operating-system user paths. Use placeholders such as
`<CLIENT_IP>`, `<CLIENT_MAC>`, `<NODE_SERIAL>`, and `<DEVICE_NAME>` in examples.

If a sensitive value is committed, rotate any affected credential immediately,
remove it from the current tree, rewrite the affected Git history, force-push the
clean history, and delete related GitHub Actions logs and artifacts.

Please report a potential security issue privately to the repository owner rather
than opening a public issue with sensitive details.
