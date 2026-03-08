"""Script de test WebSocket.

Se connecte en WebSocket et affiche les messages reçus en temps réel.
Utilisation :
    python scripts/test_ws.py [client|agent] [device_id]

Exemples :
    python scripts/test_ws.py client
    python scripts/test_ws.py agent mon-mac-01

Puis dans un autre terminal, uploadez une font :
    curl -X POST http://localhost:8000/api/fonts/upload -F "files=@tests/fixtures/ma_font.ttf"
"""

import asyncio
import json
import sys

import websockets


async def listen(url: str) -> None:
    """Se connecte au WebSocket et affiche les messages reçus."""
    print(f"Connexion à {url} ...")
    async with websockets.connect(url) as ws:
        print("Connecté ! En attente de messages...\n")
        async for raw in ws:
            msg = json.loads(raw)
            print(f"[{msg.get('type', '?')}]")
            print(json.dumps(msg.get("data", {}), indent=2, ensure_ascii=False))
            print()


def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "client"
    host = "localhost:8000"

    if mode == "agent":
        device_id = sys.argv[2] if len(sys.argv) > 2 else "test-device-001"
        url = f"ws://{host}/ws/agent/{device_id}"
    else:
        url = f"ws://{host}/ws/client"

    try:
        asyncio.run(listen(url))
    except KeyboardInterrupt:
        print("\nDéconnexion.")


if __name__ == "__main__":
    main()
