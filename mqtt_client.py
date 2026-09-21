#!/usr/bin/env python3
"""MQTT listener for Home Assistant integration debugging - with wildcard subscription."""

import argparse
import paho.mqtt.client as mqtt
import json
import time

# MQTT configuration from .env
BROKER = "192.168.1.12"
PORT = 1883
USERNAME = "kzuca"
PASSWORD = "123"

PRESET_TOPICS = [
    ("tucuxi/#", 1),                          # All Tucuxi topics
    ("homeassistant/#", 1),                   # All HA topics
    ("tucuxi/mode/alarme/set", 1),            # Alarm switch command
    ("tucuxi/mode/alarme/state", 1),          # Alarm switch state
    ("tucuxi/ha/alarm_mode", 1),              # Alarm mode sensor
    ("tucuxi/mode/viagem/set", 1),            # Viagem switch command
    ("tucuxi/mode/viagem/state", 1),          # Viagem switch state
    ("tucuxi/automation/actuator", 1),        # Actuator commands
    ("tucuxi/camera/+/event", 1),             # Camera events
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="MQTT listener for Tucuxi/HA debugging",
        epilog="""Examples:
  python mqtt_client.py                      # All topics (wildcard #)
  python mqtt_client.py -t tucuxi/#          # Only Tucuxi topics
  python mqtt_client.py -t tucuxi/camera/+/event  # Camera events only
  python mqtt_client.py --preset tucuxi      # Preset: tucuxi/# + homeassistant/#
  python mqtt_client.py --preset alarm       # Preset: alarm topics only
  python mqtt_client.py -b 192.168.1.12 -u kzuca -P 123""",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-t", "--topic", action="append", default=None,
                        help="MQTT topic to subscribe (repeatable). Default: # (all)")
    parser.add_argument("--preset", choices=["all", "tucuxi", "alarm", "camera", "predictor"],
                        help="Use a preset topic filter")
    parser.add_argument("-b", "--broker", default=BROKER,
                        help=f"MQTT broker address (default: {BROKER})")
    parser.add_argument("-p", "--port", type=int, default=PORT,
                        help=f"MQTT broker port (default: {PORT})")
    parser.add_argument("-u", "--username", default=USERNAME,
                        help=f"MQTT username (default: {USERNAME})")
    parser.add_argument("-P", "--password", default=PASSWORD,
                        help=f"MQTT password")
    parser.add_argument("-q", "--qos", type=int, default=1, choices=[0, 1, 2],
                        help="QoS level (default: 1)")
    return parser.parse_args()


def resolve_topics(args):
    if args.topic:
        return [(t, args.qos) for t in args.topic]
    preset_map = {
        "all":        [("#", 1)],
        "tucuxi":     [("tucuxi/#", 1), ("homeassistant/#", 1)],
        "alarm":      [("tucuxi/mode/alarme/set", 1), ("tucuxi/mode/alarme/state", 1),
                       ("tucuxi/ha/alarm_mode", 1), ("tucuxi/mode/viagem/set", 1),
                       ("tucuxi/mode/viagem/state", 1)],
        "camera":     [("tucuxi/camera/+/event", 1), ("homeassistant/security/#", 1)],
        "predictor":  [("tucuxi/predictions/#", 1), ("tucuxi/automation/actuator", 1)],
    }
    if args.preset:
        return [(t, args.qos) for t, _ in preset_map[args.preset]]
    return [("#", 1)]

def on_connect(client, userdata, flags, rc, properties=None):
    print(f"Connected with result code {rc}")
    if rc == 0:
        print("Connected to MQTT broker!")
        # Subscribe to topics
        for topic, qos in userdata["topics"]:
            client.subscribe(topic, qos)
            print(f"Subscribed to {topic}")
    else:
        print(f"Failed to connect, return code {rc}")

def on_message(client, userdata, msg):
    """Called when a message is received on any subscribed topic."""
    topic = msg.topic
    payload = ""
    try:
        payload = msg.payload.decode()
        
        # Try to parse as JSON
        data = None
        try:
            data = json.loads(payload)
        except json.JSONDecodeError:
            pass
        
        # Skip zero-probability predictions (noise)
        if data is not None and "probabilidade" in data and data["probabilidade"] == 0:
            return

        # Print formatted output
        print(f"\n{'='*60}")
        print(f"TOPIC: {topic}")
        if data is not None:
            print(f"PAYLOAD: {json.dumps(data, indent=2)}")
        else:
            print(f"PAYLOAD: {payload}")
        print(f"{'='*60}")
        
        # Handle common patterns
        if data is not None:
            # Alarm mode
            if "alarm_mode" in data:
                mode = data.get("alarm_mode", "")
                mode_map = {
                    "armed_home": "🟢 ARMED_HOME",
                    "armed_away": "🔴 ARMED_AWAY", 
                    "disarmed": "🟡 DISARMED"
                }
                print(f"Alarm Mode: {mode_map.get(mode, mode)}")
            
            # Switch states
            if "ON" in str(data) or "OFF" in str(data):
                switch = "ON" if "ON" in str(data) else "OFF" 
                print(f"Alarm Switch: {switch}")
            
            # Predictor probabilities
            if "probabilidade" in data:
                prob = data.get("probabilidade", 0)
                print(f"Probability: {prob}%")
        
        # Handle plain string payloads
        if data is None and ("ON" in payload or "OFF" in payload or "armed_" in payload.lower() or "disarmed" in payload.lower()):
            payload_lower = payload.lower()
            if "armed_home" in payload_lower or "armed_away" in payload_lower:
                print(f"Alarm Mode (plain): {payload.strip()}")
            elif "disarmed" in payload_lower:
                print(f"Alarm Mode (plain): {payload.strip()}")
            elif "ON" in payload:
                print(f"Alarm Switch (plain): ON")
            elif "OFF" in payload:
                print(f"Alarm Switch (plain): OFF")
                
    except Exception as e:
        print(f"Error processing message: {e}\n{topic}: {payload}")

def main():
    args = parse_args()
    topics = resolve_topics(args)

    client = mqtt.Client()
    if args.username and args.password:
        client.username_pw_set(args.username, args.password)
    
    client.user_data_set({"topics": topics})
    client.on_connect = on_connect
    client.on_message = on_message
    
    print(f"Connecting to MQTT broker at {args.broker}:{args.port}...")
    client.connect_async(args.broker, args.port, keepalive=60)
    client.loop_start()
    
    print("Listening for MQTT messages... (Press CTRL+C to stop)")
    print(f"Subscribed to: {[t[0] for t in topics]}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping...")
        client.loop_stop()
        client.disconnect()
        print("Disconnected.")

if __name__ == "__main__":
    main()