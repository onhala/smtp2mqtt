# IP Camera Configuration Guides

## Hikvision IP Cameras & NVRs

1. **Email Settings**:
   - Go to *Configuration -> Network -> Advanced Settings -> Email*.
   - **SMTP Server**: IP address of your `smtp2mqtt` host (e.g. `192.168.1.100`).
   - **SMTP Port**: `1025` (or your configured port).
   - **Authentication**: Disabled.
   - **Sender / Address**: `hikvision-driveway@home.local`.
   - **Attachment**: Check *Attached Image*.

2. **Event Linkage**:
   - Go to *Configuration -> Event -> Basic Event*.
   - Check **Enable Motion Detection**.
   - Under **Linkage Method**: Check **Send Email** and **Trigger Snapshot**.

## Dahua & Imou Cameras

1. **SMTP Settings**:
   - Go to *Network -> SMTP*.
   - Enable SMTP, set Port to `1025`, Security to `None`.
2. **Event Linkage**:
   - Enable Motion Detect, check **Send Email** and **Snapshot**.
