# EmComm-Tools Updates

Update repository for EmComm-Tools Debian Edition.

## Channels

- **stable/** - Tested releases for general use
- **beta/** - Early access for testing
- **personal/** - Private builds (VA2OPS)

## Structure
```
channel/
├── manifest.json    # File catalog with checksums
└── files/           # Actual files to download
    ├── bin/
    ├── sbin/
    └── conf/
```

## Usage

On EmComm-Tools system:
```bash
et-update check    # Check for updates
et-update          # Install updates
et-restore         # Rollback if needed
```

73 de VA2OPS
