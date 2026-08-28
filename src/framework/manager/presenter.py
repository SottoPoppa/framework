import framework.port.presentation as presentation
import framework.port.manager as manager
import framework.core.flow as flow
from framework.manager.loader import Loader

import re
import xml.etree.ElementTree as ET

import asyncio

class Manager(manager.Port):
    _session_exempt_methods = {
        "sono_stessa_risorsa",
        "split_text_and_children",
        "apply_text_and_children",
        "estrai_da_nodo",
        "estrai_attributi_tag",
        "estrai_da_xml_string",
    }
    def __init__(self, presentations: list[presentation.Port], loader:Loader, **constants):
        self.presentations = presentations
        self.loader = loader
        #self.executor = constants.get('executor')

    @flow.result()
    async def startup(self, session):
        loops = []
        for presentation in self.presentations:
            if hasattr(presentation, 'start'):
                res = await presentation.start(session)
                if flow.is_result(res):
                    if not res.get('success'):
                        return res
                    res = flow.output(res)
                if res:
                    loops.append(res)
        return loops

    @flow.result()
    async def shutdown(self , session):
        for presentation in self.presentations:
            if hasattr(presentation, 'stop'):
                await presentation.stop(session)

    @flow.result()
    async def get_view(self, session, path):
        return await self.loader.resource(path)

    @flow.result(safe_kwargs=True)
    async def get_attribute(self, session, **constants):
        driver = self._get_driver()
        return await driver.get_attribute(constants.get('widget'),constants.get('field')) if driver else None

    def _get_driver(self):
        return self.presentations[-1] if self.presentations else None

    @flow.result(safe_kwargs=True)
    async def selector(self, session, **constants):
        driver = self._get_driver()
        return await driver.selector(**constants) if driver else None

    @flow.result()
    async def render(self, session, node_id, context=None):
        driver = self._get_driver()
        if driver and hasattr(driver, 'rebuild'):
            return await driver.rebuild(node_id, context)
        return None
    
    @flow.result(safe_kwargs=True)
    async def navigate(self, session, **constants):
        driver = self._get_driver()
        return await driver.apply_route(**constants) if driver else None
        
    @flow.result()
    async def rebuild(self, session, node_id, session_id, context):
        
        driver = self._get_driver()
        if driver and hasattr(driver, 'rebuild'):
            await driver.rebuild(node_id,session_id,context)

    def sono_stessa_risorsa(self, p1: str, p2: str) -> bool:
        if not p1 or not p2:
            return False

        # 1. Uniforma le barre e rimuove slash iniziali/finali o './'
        parts1 = [p for p in p1.replace("\\", "/").split("/") if p and p != "."]
        parts2 = [p for p in p2.replace("\\", "/").split("/") if p and p != "."]

        if not parts1 or not parts2:
            return False

        # 2. Prende il percorso più corto come riferimento
        if len(parts1) <= len(parts2):
            short, long = parts1, parts2
        else:
            short, long = parts2, parts1

        # 3. Verifica che la coda (i segmenti finali) del percorso più lungo 
        #    corrisponda esattamente a tutti i segmenti del percorso più corto
        return long[-len(short):] == short

    @flow.result()
    async def reload(self, session, path):
        driver = self._get_driver()
        if driver and hasattr(driver, 'render_view') and hasattr(driver, 'routes') and hasattr(driver, 'url'):
            route_data = driver.routes.get(driver.url, {}).get('GET', {})
            view_path = route_data.get('view')
            if view_path and self.sono_stessa_risorsa(path, view_path):
                await driver.render_view(driver.url)


    def split_text_and_children(self,inner=None):
        """Separa testo e figli mantenendo l'ordine dei contenuti."""
        text_parts = []
        children = []
        for item in inner or []:
            if isinstance(item, str):
                text_parts.append(item)
            else:
                children.append(item)
        return "".join(text_parts), children

    def apply_text_and_children(self, target, text=None, children=None):
        """Applica testo e figli a un elemento XML in modo centralizzato."""
        if text is None and children is None:
            return target

        for child in list(target):
            target.remove(child)

        if text is not None:
            target.text = str(text)
            return target

        if children is not None:
            for child in children:
                if isinstance(child, ET.Element):
                    target.append(child)
                else:
                    target.text = str(child)

        return target

    def estrai_da_nodo(self, nodo_padre, target_id):
        """
        Cerca un elemento per ID partendo da un nodo già esistente
        e lo restituisce come stringa XML.
        """
        # Cerchiamo il sotto-nodo partendo dal nodo_padre
        elemento = nodo_padre.find(f".//*[@id='{target_id}']")
        
        if elemento is not None:
            # Serializziamo il nodo trovato
            return ET.tostring(elemento, encoding='unicode', method='xml').strip()
        
        return None

    def estrai_attributi_tag(self, tag_string: str):
        """
        Riceve una stringa del tag XML/DSL ed estrae tutti gli attributi in un dizionario.
        Gestisce sia virgolette singole che doppie.
        """
        # Questa regex cerca pattern tipo: chiave="valore" oppure chiave='valore'
        pattern = r'(\w+)=["\']([^"\']*)["\']'
        
        # Trova tutte le corrispondenze nella stringa
        matches = re.findall(pattern, tag_string)
        
        # Converte la lista di tuple (chiave, valore) in un dizionario
        return dict(matches)

    def estrai_da_xml_string(self, xml_string, target_id):
        if not xml_string:
            return None

        try:
            root = ET.fromstring(xml_string)
            elemento = root if root.get("id") == target_id else root.find(
                f".//*[@id='{target_id}']"
            )
            
            if elemento is not None:
                return ET.tostring(
                    elemento,
                    encoding="unicode",
                    method="xml",
                ).strip()
                
        except Exception as e:
            print(f"Errore durante l'estrazione: {e}")
        
        return None