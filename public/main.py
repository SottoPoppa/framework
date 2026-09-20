import sys
import os
import asyncio
import argparse
import subprocess

# Setup del path
cwd = os.getcwd()
sys.path.insert(1, cwd + '/src')

import framework.core.framework as framework
import framework.core.flow as flow
from framework.service.diagnostic import configure_log_file, get_logger


main_logger = get_logger("main")



def setup_core_dependencies():
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-e",
            cwd,
        ],
        check=True,
    )

async def main2(config):
    """Compatibilità per i caller esistenti: usa il percorso CLI corrente."""
    return await main(config)


async def main(config):
    if config.get("dev") or config.get("debug"):
        configure_log_file("/tmp/framework-tui.log", console=False)
        main_logger.info("Avvio CLI", config=config)

    framework_instance = framework.Framework()

    if config.get('setup'):
        setup_core_dependencies()
        return await framework_instance.install(config)

    if config.get('install'):
        return await framework_instance.install(config)

    main_logger.info("Bootstrap framework: inizio")
    app = await framework_instance.bootstrap(config)
    main_logger.info("Bootstrap framework: completato")
    try:
        if config.get('test_integration') is not None:
            tester = framework_instance.loader.get_managers().get('tester')
            result = await tester.run_integration(
                app._session,
                filter=config.get('test_integration'),
            )
            return flow.output(result)

        if config.get('test') is not None:
            tester = framework_instance.loader.get_managers().get('tester')
            result = await tester.run(
                app._session,
                filter=config.get('test'),
            )
            return flow.output(result)

        main_logger.info("Application.startup: inizio")
        await app.startup()
        return True
    except Exception as exc:
        framework_instance.logger.error("Errore critico durante l'esecuzione", exception=exc)
        return False
    finally:
        await app.shutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Avvia il framework con una configurazione specifica.")

    parser.add_argument(
        "--config",
        type=str,
        default="pyproject.toml",
        help="Percorso del file di configurazione (default: pyproject.toml)"
    )

    parser.add_argument("--debug", action="store_true", help="Abilita la modalità debug")
    parser.add_argument("--dev", action="store_true", help="Abilita la modalità dev")
    parser.add_argument("--install", action="store_true", help="Installa le dipendenze del framework")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verifica i contract in modalità strict senza avviare l'applicazione"
    )
    parser.add_argument(
        "--test",
        nargs="?",         # opzionale: accetta un valore oppure None se assente
        const="",          # se --test è dato senza valore: ""  (= tutto)
        default=None,      # se --test non è dato: None
        metavar="FILTER",
        help="Esegue i test del framework. Filtro opzionale es: services, managers, infrastructure/message"
    )
    parser.add_argument(
        "--test-integration",
        nargs="?",
        const="",
        default=None,
        metavar="FILTER",
        help="Esegue gli scenari *.integration.test.dsl. Filtro opzionale per percorso"
    )
    parser.add_argument(
        "--setup",
        action="store_true",
        help="Prepara l'ambiente e installa le dipendenze degli adapter configurati"
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Bypassa il controllo 'codice testato' degli adapter all'avvio (usare con cautela)"
    )

    args = parser.parse_args()
    args_dict = vars(args)

    '''if (
        args_dict["test_integration"] is not None
        and args_dict["config"] == "pyproject.toml"
        and os.path.exists("pyproject.integration.toml")
    ):
        args_dict["config"] = "pyproject.integration.toml"'''
    

    result = asyncio.run(main(args_dict))
    if result is False:
        sys.exit(1)