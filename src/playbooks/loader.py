"""Playbook loading and selection based on conflict classification."""
from pathlib import Path
from typing import List, Dict
from src.models.schemas import ConflictClassification, Resolvability, Domain, Nature, Form, ThreatLevel


PLAYBOOKS_DIR = Path(__file__).parent.parent.parent / "prompts" / "playbooks"


def select_playbooks(classification: ConflictClassification) -> List[str]:
    """
    Select appropriate playbooks based on conflict classification.
    Returns list of playbook filenames (e.g., ['eft.md', 'gottman.md']).
    
    Logic from conflict_mapping.md:
    1. Check Red Flags first
    2. Primary approach by Nature
    3. Add secondary by Form/Resolvability    
    4. Adjust by Domain
    """
    playbooks = []
    
    # Step 1: Check Red Flags
    if _is_red_flag(classification):
        # Should redirect to professional, no playbooks
        return []
    
    # Step 2: Primary approach by Nature
    if classification.nature == Nature.EMOTIONAL:
        playbooks.append("eft.md")
    elif classification.nature == Nature.RATIONAL:
        playbooks.append("cbt.md")
    
    # Step 3: Add secondary by Form/Resolvability
    if classification.form == Form.HIDDEN:
        # Hidden conflicts need TA or Psychodynamic
        playbooks.append("transactional_analysis.md")
    
    if classification.resolvability == Resolvability.PERPETUAL:
        # Perpetual conflicts need Gottman or Existential
        if "gottman.md" not in playbooks:
            playbooks.append("gottman.md")
        playbooks.append("existential.md")
    
    if classification.resolvability == Resolvability.GRIDLOCKED:
        # Gridlocked needs EFT or Systemic
        if "eft.md" not in playbooks:
            playbooks.append("eft.md")
    
    # Step 4: Adjust by Domain
    if classification.domain == Domain.RELATIVES or classification.domain == Domain.PARENTING:
        # Family conflicts need Systemic
        playbooks.append("systemic.md")
    
    if classification.domain == Domain.FUTURE_PLANS:
        # Value conflicts need Existential
        if "existential.md" not in playbooks:
            playbooks.append("existential.md")
    
    # Communication issues benefit from Gottman
    if classification.domain in [Domain.TIME_ATTENTION, Domain.HOUSEHOLD]:
        if "gottman.md" not in playbooks:
            playbooks.append("gottman.md")
    
    # Remove duplicates, keep order
    seen = set()
    unique_playbooks = []
    for pb in playbooks:
        if pb not in seen:
            seen.add(pb)
            unique_playbooks.append(pb)
    
    # Limit to 2 primary playbooks
    return unique_playbooks[:2]


def _is_red_flag(classification: ConflictClassification) -> bool:
    """Check if classification indicates need for professional help."""
    # High threat + foundational = potential for serious issues
    if classification.threat_level == ThreatLevel.FOUNDATIONAL:
        # In real system, would check for specific domains like abuse, addiction
        # For now, we allow foundational conflicts but will guide carefully
        return False
    return False


def load_playbook(playbook_name: str) -> str:
    """Load playbook content from file."""
    playbook_path = PLAYBOOKS_DIR / playbook_name
    
    if not playbook_path.exists():
        raise FileNotFoundError(f"Playbook not found: {playbook_name}")
    
    with open(playbook_path, "r", encoding="utf-8") as f:
        return f.read()


def load_selected_playbooks(classification: ConflictClassification) -> str:
    """
    Select and load playbooks based on classification.
    Returns combined playbook text.
    """
    playbook_names = select_playbooks(classification)
    
    if not playbook_names:
        return "# No Specialized Playbook\n\nUse general therapeutic approach. Focus on safety and referral to professional."
    
    combined = ""
    for name in playbook_names:
        try:
            content = load_playbook(name)
            combined += f"\n\n---\n\n{content}"
        except FileNotFoundError:
            print(f"Warning: Playbook {name} not found, skipping")
            continue
    
    return combined


# Mapping for reference (used by selection logic)
PLAYBOOK_MAPPING: Dict[str, Dict[str, List[str]]] = {
    "nature": {
        "rational": ["cbt.md", "gottman.md"],
        "emotional": ["eft.md"],
    },
    "form": {
        "hidden": ["transactional_analysis.md", "psychodynamic.md"],
        "open": ["gottman.md", "cbt.md"],
    },
    "resolvability": {
        "resolvable": ["cbt.md", "gottman.md"],
        "perpetual": ["gottman.md", "existential.md"],
        "gridlocked": ["eft.md", "systemic.md", "transactional_analysis.md"],
    },
    "domain": {
        "money": ["cbt.md", "gottman.md"],
        "sex": ["eft.md", "gottman.md"],
        "parenting": ["systemic.md", "gottman.md"],
        "relatives": ["systemic.md"],
        "household": ["cbt.md", "gottman.md"],
        "time_attention": ["eft.md", "gottman.md"],
        "future_plans": ["existential.md", "gottman.md"],
    },
}

