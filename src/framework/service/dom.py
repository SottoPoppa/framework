"""Primitive DOM indipendenti dal livello di presentation."""

import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator


def parse(text: str) -> ET.Element:
    """Parsa una stringa XML e restituisce la radice DOM."""
    return ET.fromstring(text)


def parse_error() -> type[ET.ParseError]:
    """Restituisce l'eccezione sollevata dal parser XML."""
    return ET.ParseError


def serialize(node: ET.Element) -> str:
    """Serializza un nodo DOM come XML."""
    return ET.tostring(node, encoding="unicode", method="xml")


def tag_name(node: ET.Element) -> str:
    """Restituisce il nome locale di un tag XML."""
    return node.tag.split("}")[-1]


def attribute_name(name: str) -> str:
    """Restituisce il nome locale di un attributo XML."""
    return name.split("}")[-1]


def attributes(node: ET.Element) -> dict[str, str]:
    """Restituisce gli attributi di un nodo XML."""
    return node.attrib


def text(node: ET.Element) -> str | None:
    """Restituisce il testo diretto di un nodo XML."""
    return node.text


def children(node: ET.Element) -> list[ET.Element]:
    """Restituisce i figli diretti di un nodo XML."""
    return list(node)


def has_children(node: ET.Element) -> bool:
    """Indica se un nodo XML contiene figli diretti."""
    return bool(len(node))


def iter_nodes(node: ET.Element) -> Iterator[ET.Element]:
    """Itera ricorsivamente i nodi di un albero DOM."""
    return node.iter()


def element_type() -> type[ET.Element]:
    """Restituisce il tipo concreto dei nodi XML."""
    return ET.Element


def replace_children(node: ET.Element, children: Iterable[ET.Element]) -> None:
    """Sostituisce i figli diretti di un nodo."""
    for child in list(node):
        node.remove(child)
    for child in children:
        node.append(child)


def set_text(node: ET.Element, value: str | None) -> None:
    """Imposta il testo diretto di un nodo."""
    node.text = value


def append_child(node: ET.Element, child: ET.Element) -> None:
    """Aggiunge un figlio diretto a un nodo."""
    node.append(child)


def find_by_id(node: ET.Element, target_id: str) -> ET.Element | None:
    """Cerca il primo discendente con l'attributo XML id indicato."""
    return node.find(f".//*[@id='{target_id}']")


def attributes_from_tag(tag: str | ET.Element) -> dict[str, str]:
    """Restituisce gli attributi del tag XML o del nodo indicato."""
    if isinstance(tag, str):
        tag = parse(tag)
    return dict(attributes(tag))
