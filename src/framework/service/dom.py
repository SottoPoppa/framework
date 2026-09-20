"""Primitive DOM indipendenti dal livello di presentation."""

import xml.etree.ElementTree as ET


def parse(text: str):
    """Parsa una stringa XML e restituisce la radice DOM."""
    return ET.fromstring(text)


def parse_error():
    """Restituisce l'eccezione sollevata dal parser XML."""
    return ET.ParseError


def serialize(node) -> str:
    """Serializza un nodo DOM come XML."""
    return ET.tostring(node, encoding="unicode", method="xml")


def tag_name(node) -> str:
    """Restituisce il nome locale di un tag XML."""
    return node.tag.split("}")[-1]


def attribute_name(name: str) -> str:
    """Restituisce il nome locale di un attributo XML."""
    return name.split("}")[-1]


def attributes(node):
    """Restituisce gli attributi di un nodo XML."""
    return node.attrib


def text(node):
    """Restituisce il testo diretto di un nodo XML."""
    return node.text


def children(node):
    """Restituisce i figli diretti di un nodo XML."""
    return list(node)


def has_children(node) -> bool:
    """Indica se un nodo XML contiene figli diretti."""
    return bool(len(node))


def iter_nodes(node):
    """Itera ricorsivamente i nodi di un albero DOM."""
    return node.iter()


def element_type():
    """Restituisce il tipo concreto dei nodi XML."""
    return ET.Element


def replace_children(node, children) -> None:
    """Sostituisce i figli diretti di un nodo."""
    for child in list(node):
        node.remove(child)
    for child in children:
        node.append(child)


def set_text(node, value) -> None:
    """Imposta il testo diretto di un nodo."""
    node.text = value


def append_child(node, child) -> None:
    """Aggiunge un figlio diretto a un nodo."""
    node.append(child)


def find_by_id(node, target_id):
    """Cerca il primo discendente con l'attributo XML id indicato."""
    return node.find(f".//*[@id='{target_id}']")


def attributes_from_tag(tag):
    """Restituisce gli attributi del tag XML o del nodo indicato."""
    if isinstance(tag, str):
        tag = parse(tag)
    return dict(attributes(tag))
