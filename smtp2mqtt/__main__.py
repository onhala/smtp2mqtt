import os
import sys
import asyncio
from smtp2mqtt.platform.loxberry.adapter import LoxBerryPlatformAdapter
from smtp2mqtt.platform.docker.adapter import DockerPlatformAdapter
import smtp2mqtt

def get_platform_adapter():
    """Detects running environment and instantiates appropriate PlatformAdapter."""
    if "LBHOME" in os.environ or os.path.exists("/opt/loxberry"):
        return LoxBerryPlatformAdapter()
    return DockerPlatformAdapter()

def main():
    """Entrypoint function."""
    adapter = get_platform_adapter()
    adapter.initialize()
    if hasattr(smtp2mqtt, "main"):
        smtp2mqtt.main()

if __name__ == "__main__":
    main()

