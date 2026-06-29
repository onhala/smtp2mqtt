#!/usr/bin/env python3
import asyncio
import smtplib
import sys
import threading
import time
from email.message import EmailMessage

async def handle_mqtt_client(reader, writer):
    print("🤖 [Mock MQTT] Client connected!")
    try:
        while True:
            data = await reader.read(2048)
            if not data:
                break
            
            # Check for CONNECT packet (0x10)
            if data[0] == 0x10:
                print("🤖 [Mock MQTT] Received CONNECT packet. Accepting connection...")
                # Respond with CONNACK (0x20, 0x02, 0x00, 0x00 - connection accepted)
                writer.write(b"\x20\x02\x00\x00")
                await writer.drain()
            # Check for PUBLISH packet (0x30)
            elif (data[0] & 0xF0) == 0x30:
                # Simple parsing
                try:
                    # remaining length parsing
                    pos = 1
                    multiplier = 1
                    remaining_length = 0
                    while True:
                        byte = data[pos]
                        remaining_length += (byte & 127) * multiplier
                        pos += 1
                        multiplier *= 128
                        if (byte & 128) == 0:
                            break
                    
                    topic_len = (data[pos] << 8) | data[pos+1]
                    pos += 2
                    topic = data[pos:pos+topic_len].decode('utf-8', errors='ignore')
                    pos += topic_len
                    
                    # Remaining bytes are the payload
                    payload_bytes = data[pos:pos + remaining_length - 2 - topic_len]
                    payload = payload_bytes.decode('utf-8', errors='ignore')
                    print(f"📥 [Mock MQTT] PUBLISH received on topic '{topic}': '{payload}'")
                except Exception as e:
                    print(f"⚠️ [Mock MQTT] Failed to parse PUBLISH packet: {e} (raw length: {len(data)})")
            elif data[0] == 0xC0:
                # PINGREQ
                print("⚙️ [Mock MQTT] Received PINGREQ. Sending PINGRESP...")
                writer.write(b"\xD0\x00")
                await writer.drain()
            elif data[0] == 0xE0:
                # DISCONNECT
                print("⚙️ [Mock MQTT] Received DISCONNECT.")
                break
            else:
                print(f"⚙️ [Mock MQTT] Received packet type {hex(data[0])}")
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"❌ [Mock MQTT] Connection error: {e}")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        print("🤖 [Mock MQTT] Client disconnected.")

async def start_broker():
    server = await asyncio.start_server(handle_mqtt_client, "127.0.0.1", 1883)
    addr = server.sockets[0].getsockname()
    print(f"🚀 [Mock MQTT] Broker running on {addr[0]}:{addr[1]}")
    async with server:
        await server.serve_forever()

def send_test_email(smtp_port=1025, with_attachment=True):
    print(f"📧 [Email Sender] Connecting to SMTP server on 127.0.0.1:{smtp_port}...")
    try:
        msg = EmailMessage()
        msg["Subject"] = "🚨 Security Gateway - Motion detected in restricted zone!"
        msg["From"] = "camera@example.com"
        msg["To"] = "recipient@example.com"
        
        # HTML body
        html_content = """
        <html>
        <body style="font-family: sans-serif; background-color: #0f172a; color: #f8fafc; padding: 20px; border-radius: 10px;">
            <h2 style="color: #ef4444;">🚨 Autonomous Security Gateway</h2>
            <p>Motion has been detected in a restricted zone.</p>
            <p><b>Timestamp:</b> 2026-06-29 13:33:00</p>
            <p><b>Sensors:</b> LiDAR fusion & vision motion cameras</p>
            <p>The attachment contains the current snapshot from the camera system.</p>
        </body>
        </html>
        """
        msg.set_content("Motion detected in a restricted zone!")
        msg.add_alternative(html_content, subtype="html")
        
        if with_attachment:
            # Minimal valid 1x1 black pixel JPEG byte content
            fake_jpg = (
                b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00"
                b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08"
                b"\n\x0c\x14\x08\x08\x0b\x0b\x17\x11\x12\r\x14\x1d\x11\x16\x16\x1d"
                b"[\x1f\x23\x1b#\x1f\x1d\x1d#\x23[\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\\"
                b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
                b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00"
                b"\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
                b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x37\xff\xd9"
            )
            msg.add_attachment(fake_jpg, maintype="image", subtype="jpeg", filename="vision_threat.jpg")
            print("📎 [Email Sender] Added image attachment: vision_threat.jpg")
 
        with smtplib.SMTP("127.0.0.1", smtp_port, timeout=5) as smtp:
            smtp.ehlo()
            smtp.send_message(msg)
        print("✅ [Email Sender] Email sent successfully!")
    except Exception as e:
        print(f"❌ [Email Sender] Failed to send email: {e}")

def main():
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
        if mode == "broker":
            try:
                asyncio.run(start_broker())
            except KeyboardInterrupt:
                print("\nStopping Mock MQTT Broker...")
        elif mode == "email":
            port = 1025
            if len(sys.argv) > 2:
                try:
                    port = int(sys.argv[2])
                except ValueError:
                    pass
            send_test_email(port)
        else:
            print("Usage: python simulate.py [broker | email [port]]")
    else:
        print("="*60)
        print("          Security Gateway smtp2mqtt Local Testing & Simulation")
        print("="*60)
        print("Starting local mock MQTT broker on port 1883...")
        
        # Start broker in a separate background thread
        broker_thread = threading.Thread(target=lambda: asyncio.run(start_broker()), daemon=True)
        broker_thread.start()
        
        time.sleep(0.5)
        
        print("\nSimulation tool is ready for testing.")
        print("You can now start smtp2mqtt in another terminal:")
        print("  python smtp2mqtt.py")
        print("And monitor the status at: http://localhost:8080\n")
        print("Commands in this console:")
        print("  [E] - Send test email with image attachment (saved as attachment)")
        print("  [Q] - Quit simulation")
        print("-"*60)
        
        try:
            while True:
                choice = input("Enter command [E/Q]: ").strip().upper()
                if choice == "E":
                    send_test_email()
                elif choice == "Q":
                    print("Stopping simulation...")
                    break
        except KeyboardInterrupt:
            print("\nSimulation terminated.")

if __name__ == "__main__":
    main()
