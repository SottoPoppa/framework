modifivare loader migliorando come veongo caricati

aggiugere supporto per i file diertatemnmte collegati e i file indirettamente collegati 

separare bene infra /  frame / app

migliorare log !

finire flow. con schemi!

## Migrazione typing rigoroso

1. [x] Attivare Pyright per Python 3.11 in modalita strict; baseline iniziale 4.583 errori, ultima misura 4.147.
2. [x] Usare Protocol per i Port strutturali; mantenere le ABC dove stato o comportamento runtime fanno parte del contratto.
3. [x] Tipizzare un primo slice core: FlowResult/TypeGuard, Dag, Session e DagRunner; test mirati runner e snapshot superati.
4. [x] Tipizzare i contratti verificabili di core/interpreter.py; 6 test mirati superati e diagnostici del file ridotti da 186 a 37. I payload e dispatch DSL/runtime restano dinamici; rimane un diagnostico locale sul valore eterogeneo in evaluate_named.
5. [x] Tipizzare il dispatch verificabile in core/evaluation.py; 5 test mirati superati e diagnostici del file ridotti da 23 a 21. Restano Any nei risultati DSL, negli input ricorsivi eterogenei e nella tabella Callable degli operatori.
6. [x] Tipizzare DagDefinition.from_nodes in core/model.py; diagnostici strict del file ridotti da 30 a 13. Aggiunto il ritorno None ai costruttori Registry e Scope; restano rispettivamente 7 e 12 diagnostici strict nei traversal dinamici.
	Verifiche: test factory superato, 5 round-trip del codec superati e smoke check Registry/Scope superato. Pyright globale: 4.147 errori, 19 in meno rispetto alla misura precedente di 4.166. Suite unittest: 144 test, 3 failure e 3 errori. Il rerun mirato conferma due problemi esterni a questi moduli: dipendenza NoneType nel loader/flow e import mancante di infrastructure.network.neural.encefalo.

venv/bin/python3.11 public/main.py --dev --skip-verify

## Revisione statica

Esito, finding e limiti dell'analisi sono raccolti in [report.md](report.md).
La review non ha eseguito le suite DSL o gli integration test; i difetti
runtime descritti nel report restano da verificare e correggere separatamente.