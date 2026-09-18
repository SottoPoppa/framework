"""
0-99	Percezione (Ontologico)	Riconoscimento "Cos'è" (Corteccia Temporale).
100-199	Navigazione (Spazio-Temporale)	Posizionamento e contesto (Ippocampo/Parietale).
200-299	Esecutivo (Funzionale)	Simulazione d'azione/Uso (Corteccia Premotoria).
300-399	Affettivo (Valutativo)	Emozioni e piacere/dolore (Amigdala/Limbico).
400-499	Sociale (Relazionale)	Empatia e Gerarchie (Prefrontale Mediale).
500-599	Linguistico (Sintattico)	Struttura e grammatica (Area di Broca/Wernicke).
600-699	Memoria (Episodica)	Ricordi personali e "Cosa ho visto prima".
700-799	Logico (Deduttivo)	Regole, causa-effetto e astrazione matematica.
800-899	Attentivo (Focus)	Filtro: cosa è importante ora? (Dorsal Attention).
900-999	Meta-Cognitivo (Talamo)	Il supervisore: coordina gli altri 9 moduli."""

# Modulo 1: Navigazione (Spazio-Temporale)

spazio = [

]


#Modulo 6: Memoria (Episodica)
memoria = [
    #0-9: Integrazione TemporaleRecente, 
    "Remoto", "Immediato", "Periodico", "Ricorrente", "Puntuale", "Episodico", "Sequenziale", "Sincrono", "Asincrono"
    #10-19: Contesto EsperienzialeLuogo, 
    "Situazione", "Evento", "Soggetto", "Oggetto", "Ambiente", "Atmosfera", "Condizioni", "Trigger", "Risultato"
    #20-29: Intensità MnemonicaVivido, 
    "Sbiadito", "Distorto", "Preciso", "Dettagliato", "Sintetico", "Emotivo", "Razionale", "Primario", "Secondario"
    #30-39: AssociazioneLegato a persona, 
    "Legato a luogo", "Legato a emozione", "Legato a fatto", "Contrapposto", "Simile", "Causa-Effetto", "Derivato", "Casuale", "Strutturato"
    #40-49: Stato della MemoriaArchiviato, 
    "Attivo", "Soppresso", "Ricordato", "Dimenticato", "Rielaborato", "Integro", "Parziale", "Corrotto", "Modificato"
    #60-69: AccessibilitàFacile, 
    "Difficile", "Immediato", "Richiede sforzo", "Indotto", "Esposto", "Celato", "Pubblico", "Privato", "Condiviso"
    #70-79: VeridicitàReale, 
    "Fittizio", "Interpretato", "Sognato", "Allucinatorio", "Verificato", "Documentato", "Opinabile", "Incerto", "Ipoteizzato"
    #80-89: Impatto MnemonicoTrasformativo, 
    "Informativo", "Insignificante", "Fondamentale", "Critico", "Utile", "Dannoso", "Formativo", "Effimero", "Duraturo"
    #90-99: RiconoscimentoIdentificato
    "Sconosciuto", "Familiare", "Confuso", "Distinto", "Indistinto", "Catalogato", "Non categorizzato", "Ripetuto", "Unico"
]



#Modulo 7: Logico (Deduttivo)
Logico = [
    #0-9: Operazioni Logiche
    "Congiunzione (AND)", "Disgiunzione (OR)", "Negazione (NOT)", "Implicazione", "Equivalenza", "XOR", "NAND", "NOR", "Condizione", "Asserzione",
    #10-19: Causalità
    "Causa", "Effetto", "Correlazione", "Concause", "Precedenza", "Conseguenza", "Feedback", "Deterministico", "Stocastico", "Finalistico",
    #20-29: Validità
    "Vero", "Falso", "Probabile", "Possibile", "Impossibile", "Necessario", "Contingente", "Ambiguo", "Indeterminato", "Contraddittorio",
    #30-39: Strutture Inferenziali
    "Deduzione", "Induzione", "Abduzione", "Sillogismo", "Analogia", "Generalizzazione", "Astrazione", "Esemplificazione", "Teorema", "Ipotesi",
    #40-49: Analisi Critica
    "Coerenza", "Incoerenza", "Fallacia", "Bias", "Validazione", "Falsificabilità", "Verifica", "Evidenza", "Argomento", "Controargomento",
    #50-59: Quantificazione
    "Universale", "Esistenziale", "Numerico", "Frazionario", "Infinito", "Nullo", "Incrementale", "Decrescente", "Proporzionale", "Limite",
    #60-69: Relazioni Matematiche
    "Uguaglianza", "Disuguaglianza", "Inclusione", "Intersezione", "Unione", "Set", "Funzione", "Inverso", "Derivato", "Integrale",
    #70-79: Risoluzione Problemi
    "Algoritmo", "Euristica", "Ottimizzazione", "Vincolo", "Soluzione", "Bottleneck", "Iterazione", "Scomposizione",
    #90-99: Verità Epistemica
    "Assioma", "Postulato", "Opinione", "Fatto", "Dogma", "Credenza", "Consenso", "Dubbio", "Evidenza", "Dimostrazione"
]

#Modulo 8: Attentivo (Focus)
attentivo = [
    #0-9: Salienza Stimolo
    "Rilevante", "Irrilevante", "Saliente", "Marginale", "Centrale", "Urgente", "Critico", "Banale", "Prioritario", "Secondario",
    #10-19: Orientamento Attentivo	
    "Selettivo", "Diviso", "Sostenuto", "Alternato", "Esterno", "Interno", "Volontario", "Automatico", "Periferico", "Focale",
    #20-29: Intensità/Energia
    "Vigile", "Distratto", "Concentrato", "Affaticato", "Iper-attivo", "Stabile", "Oscillante", "Profondo", "Superficiale", "Resiliente",
    #30-39: Filtro Selettivo
    "Inibitorio", "Facilitatorio", "Soppressore", "Amplificatore", "Discriminante", "Noise-cancelling", "Selettivo", "Ampio", "Stretto", "Sincrono",
    #40-49: Gestione Carico
    "Sovraccarico", "Ottimizzato", "Sottoutilizzato", "Bilanciato", "Bloccato",("Fluido"), ("Sotto-sforzo"), ("Gestibile"), ("Critico"), ("Gestito"),
    #50-59: Trigger/Innesco	Attivante, Dissuasivo, Neutro, Inatteso, Atteso, Periodico, Casuale, Contestuale,
   ("Attivante"), ("Dissuasivo"), ("Neutro"), ("Inatteso"), ("Atteso"), ("Periodico"), ("Casuale"), ("Contestuale"), ("Personale"), ("Generale")
    #60-69: persistenza del Focus	
    "Durevole", "Breve", "Transitorio", "Ciclico", "Interrotto", "Continuo", "Fissazione", "Esplorativo", "Rigido", "Flessibile"
    #70-79: Direzione dell'Attenzione	
    "Ego-riferito", "Allo-riferito", "Task-oriented", "Goal-oriented", "Data-driven", "Concept-driven", "Spaziale", "Temporale", "Sociale", "Logico"
    #80-89: Qualità dell'Input	
    "Chiara", "Confusa", "Rumorosa", "Distorta", "Completa", "Parziale", "Ambigua", "Precisa", "Evidente", "Occulta"
    #90-99: Monitoraggio Focus	
    "Auto-regolato", "Esterno", "Feedback-loop", "Correttivo", "Adattivo", "Passivo", "Attivo", "Metacognitivo", "Inconsapevole", "Consapevole"
]

#Modulo 9: Meta-Cognitivo (Supervisore)
meta = [
    #0-9: Monitoraggio Status	Attivo, Inattivo, Error-mode, Overload, Sotto-carico, Sincronizzato, Desincronizzato, Pronto, Risorse-critiche, Ottimale
    "Attivo", "Inattivo", "Error-mode", "Overload", "Sotto-carico", "Sincronizzato", "Desincronizzato", "Pronto", "Risorse-critiche", "Ottimale",
    #10-19: Controllo Modulare	Routing, Inibizione, Attivazione, Sinergia, Isolamento, Integrazione, Prioritizzazione, Bilanciamento, Feedback, Bypass
    "Routing", "Inibizione", "Attivazione", "Sinergia", "Isolamento", "Integrazione", "Prioritizzazione", "Bilanciamento", "Feedback", "Bypass",
    #20-29: Autocoscienza/Bias	Consapevole, Bias-check, Limiti-propri, Auto-correzione, Ipotesi-di-sbaglio, Obiettività, Soggettività, Trasparenza, Opacità, Limite
    "Consapevole", "Bias-check", "Limiti-propri", "Auto-correzione", "Ipotesi-di-sbaglio", "Obiettività", "Soggettività", "Trasparenza", "Opacità", "Limite",
    #30-39: Pianificazione Strategica	Goal-setting, Valutazione-rischi, Costo-beneficio, Flessibilità, Determinazione, Lungimiranza, Adattabilità, Coerenza, Focalizzazione, Strategia
    "Goal-setting", "Valutazione-rischi", "Costo-beneficio", "Flessibilità", "Determinazione", "Lungimiranza", "Adattabilità", "Coerenza", "Focalizzazione", "Strategia",
    #40-49: Gestione Decisionale	Decisione-rapida, Riflessiva, Delegata, Sospesa, Risolutiva, Gerarchica, Distribuita, Consensus, Arbitraria, Ragionata
    "Decisione-rapida", "Riflessiva', 'Delegata', 'Sospesa', 'Risolutiva', 'Gerarchica', 'Distribuita', 'Consensus', 'Arbitraria', 'Ragionata',
    #50-59: Apprendimento (Meta)	Ottimizzazione, Aggiornamento, Consolidamento, Error-analysis, Pattern-recognition,
    "Ottimizzazione", "Aggiornamento",("Consolidamento"), ("Error-analysis"), ("Pattern-recognition"), ("Adattamento"), ("Plasticità"), ("Stabilità"), ("Riflessione"), ("Sintesi")
    #60-69: Etica/Vincoli	
    "Sicurezza", "Etica-principale", "Vincolo-legale", "Direttive-umane", "Protezione-utente", "Responsabilità", "Neutralità", "Tracciabilità", "Compliance", "Divieto"
    #70-79: Stato del Sistema
    "Coerente", "Contraddittorio", "Frammentato", "Integrato", "Evolutivo", "Statico", "Stabile", "Instabile", "Funzionale", "Disfunzionale",
    #80-89: Relazione con l'Estern
    "Trasparente", "Chiuso", "Collaborativo", "Autoritario", "Servile", "Indipendente", "Adattivo", "Reattivo", "Distaccato", "Empatico",
    #90-99: Sintesi Globale	
    "Visione-d'insieme", "Dettaglio", "Astratto", "Concreto", "Multidimensionale", "Lineare", "Olistico", "Riduzionista", "Profondo", "Finale"
]

class Encefalo:
    def __init__(self):
        self.moduli = {
            "Modulo 2: Esecutivo (Funzionale)": [
                [(200+i, nome) for i, nome in enumerate()],
            ],
            "Modulo 6: Memoria (Episodica)": [
                [(600+i, nome) for i, nome in enumerate()],
            ],
            "Modulo 8: Attentivo (Focus)": [
                [(800+i, nome) for i, nome in enumerate()],
            ],
            "Modulo 9: Meta-Cognitivo (Talamo)": [
                [(900+i, nome) for i, nome in enumerate()],
            ]
        }