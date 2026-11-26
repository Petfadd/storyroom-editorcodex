"""Conservative editorial role gates for automatic documentary portrait overlays.

A link or frame in a footage sheet is a source asset, NOT proof of identity or role.
Support people (police, lawyers, pastors, neighbours) remain video clips.
"""
from __future__ import annotations
import re

_FEATURED = re.compile(r"\b(?:victim|deceased|killed|survivor|suspect|accused|defendant|"
                       r"father|mother|daughter|son|brother|sister|grandparent|grandmother|grandfather|"
                       r"aunt|uncle|cousin|wife|husband|stepfather|stepmother|"
                       r"family member|relative)\b", re.I)
_PROTECTED = re.compile(r"\b(?:protected minor|protected juvenile|juvenile|underage|"
                        r"minor defendant|15[- ]year[- ]old suspect|14[- ]year[- ]old suspect)\b", re.I)
_SUPPORT = re.compile(r"\b(?:victim['’]s friend|victim['’]s neighbor|friend of the victim|"
                      r"family friend|police|detective|officer|investigator|lawyer|attorney|"
                      r"prosecutor|judge|pastor|minister|councilman|councilwoman|"
                      r"community leader|neighbor|neighbour|witness|reporter|journalist)\b", re.I)


def featured_role(role: str) -> bool:
    """Only unambiguous core-case classifications qualify for auto portraits.

    Metadata is not independent identity verification; unknown roles stay clips-only.
    """
    s = ' '.join(str(role or '').split())
    if not s or _PROTECTED.search(s):
        return False
    if _SUPPORT.search(s) and not re.search(r"\b(?:survivor|family member|relative)\b", s, re.I):
        return False
    return bool(_FEATURED.search(s))


def source_is_supporting(description: str) -> bool:
    """Protect against legacy descriptions turning 'victim’s friend' into 'Victim'."""
    s = ' '.join(str(description or '').split())
    return bool(re.search(r"\b(?:victim['’]s friend|victim['’]s neighbor|"
                          r"friend of (?:the )?victim|family friend|neighbou?r interview)\b", s, re.I))


def featured_person(person: dict, assets=()) -> bool:
    if not featured_role(person.get('role')):
        return False
    source = person.get('sheet_source')
    if source:
        for a in assets or ():
            provenance = a.get('provenance') or {}
            if provenance.get('source_id') == source and source_is_supporting(provenance.get('description')):
                return False
    return True


def in_story(name: str, project: dict) -> bool:
    """Require a literal complete-name mention in narration SRT or production script."""
    name = ' '.join(str(name or '').split())
    if len(name.split()) < 2:
        return False
    sources = [b.get('text', '') for b in ((project.get('srt') or {}).get('blocks') or [])]
    sources.append((project.get('production_script') or {}).get('text', ''))
    pattern = re.compile(r'(?<![\w])' + r'\s+'.join(map(re.escape, name.split())) + r'(?![\w])', re.I)
    return any(pattern.search(s or '') for s in sources)
