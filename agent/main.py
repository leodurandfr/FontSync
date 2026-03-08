"""Point d'entrée de l'agent FontSync — scan initial + push."""

from __future__ import annotations

import logging
import sys

from agent.config import AgentConfig
from agent.discovery import discover_fonts
from agent.scanner import scan_fonts
from agent.sync_client import SyncClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("agent")

# Réduire le bruit des libs HTTP
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def print_progress(current: int, total: int, *, label: str = "Progression") -> None:
    """Affiche la progression dans le terminal."""
    bar_len = 40
    filled = int(bar_len * current / total) if total > 0 else 0
    bar = "█" * filled + "░" * (bar_len - filled)
    pct = (current / total * 100) if total > 0 else 0
    sys.stdout.write(f"\r  {label} : [{bar}] {current}/{total} ({pct:.0f}%)")
    sys.stdout.flush()
    if current == total:
        sys.stdout.write("\n")


def main() -> None:
    """Orchestre le scan initial et le push vers le serveur."""
    print("╔══════════════════════════════════════╗")
    print("║        FontSync Agent v0.1.0         ║")
    print("╚══════════════════════════════════════╝")
    print()

    # 1. Charger la configuration
    config = AgentConfig.load()
    print(f"  Serveur : {config.server_url}")
    print(f"  Dossiers : {', '.join(config.directories)}")
    print()

    with SyncClient(config) as client:
        # 2. Enregistrement du device
        print("→ Enregistrement du device...")
        try:
            device_data = client.register_device()
        except Exception as e:
            print(f"  ✗ Impossible de contacter le serveur : {e}")
            print(f"  Vérifiez que le serveur est démarré sur {config.server_url}")
            sys.exit(1)

        device_id = device_data["id"]
        config.device_id = device_id
        config.save()
        print(f"  ✓ Device enregistré : {device_data['name']} (id={device_id})")
        print()

        # 3. Découverte des fonts
        print("→ Scan des polices en cours...")
        discovered = discover_fonts(config.directories, config.ignore_patterns)
        print(f"  {len(discovered)} fichiers de polices détectés")
        print()

        if not discovered:
            print("  Aucune police trouvée dans les dossiers surveillés.")
            return

        # 4. Hashing SHA-256
        print("→ Calcul des empreintes SHA-256...")
        scanned = scan_fonts(
            discovered,
            on_progress=lambda c, t: print_progress(c, t, label="Hash"),
        )
        print(f"  ✓ {len(scanned)} polices analysées")
        print()

        # 5. Delta sync
        print("→ Comparaison avec le serveur...")
        try:
            delta = client.delta_sync(device_id, scanned)
        except Exception as e:
            print(f"  ✗ Erreur delta sync : {e}")
            sys.exit(1)

        unknown = set(delta.get("unknown_to_server", []))
        missing = delta.get("missing_on_device", [])
        already = delta.get("already_synced", 0)

        print(f"  Nouvelles pour le serveur : {len(unknown)}")
        print(f"  Déjà synchronisées : {already}")
        print(f"  Disponibles depuis le serveur : {len(missing)}")
        print()

        # 6. Push des fonts inconnues du serveur
        if unknown and config.auto_push:
            print(f"→ Envoi de {len(unknown)} polices vers le serveur...")
            pushed, duplicates, errors = client.push_fonts(
                device_id,
                scanned,
                unknown,
                on_progress=lambda c, t: print_progress(c, t, label="Push"),
            )
            print(f"  ✓ {pushed} envoyées, {duplicates} doublons, {errors} erreurs")
            print()
        elif unknown:
            print(f"  ⏸ {len(unknown)} polices à envoyer (auto_push désactivé)")
            print()

        # 7. Résumé final
        print("╔══════════════════════════════════════╗")
        print("║          Scan terminé                ║")
        print("╠══════════════════════════════════════╣")
        print(f"║  Polices détectées : {len(scanned):>14} ║")
        print(f"║  Déjà sur le serveur : {already:>12} ║")
        if unknown and config.auto_push:
            print(f"║  Nouvelles envoyées : {pushed:>13} ║")
            if errors:
                print(f"║  Erreurs d'envoi : {errors:>16} ║")
        print(f"║  Disponibles à puller : {len(missing):>11} ║")
        print("╚══════════════════════════════════════╝")


if __name__ == "__main__":
    main()
