import sys
import os
import asyncio
import argparse
import subprocess

# Setup del path
cwd = os.getcwd()
sys.path.insert(1, cwd + '/src')



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

async def main(config):

    if config.get('setup'):
        setup_core_dependencies()
        from framework.manager.loader import Loader
        loader_instance = Loader()
        await loader_instance.install(config)
        return
    else:
        from framework.manager.loader import Loader
        loader_instance = Loader()
        

    if config.get('install'):
        await loader_instance.install(config)
        return

    if config.get('verify'):
        return await loader_instance.verify_contracts(config)

    app = await loader_instance.bootstrap(config)

    try:
        if config.get('test_integration') is not None:
            return await loader_instance.run_integration_tests(config.get('test_integration'))
        if config.get('test') is not None:
            return await loader_instance.run_tests(config.get('test'))

        await app.startup()
    except Exception as e:
        print(f"[!] Errore critico: {e}")
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