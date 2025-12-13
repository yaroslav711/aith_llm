"""Conflict classification logic."""
import json
from typing import Optional
from src.models.schemas import ConflictClassification, Resolvability, Domain, Nature, Form, ThreatLevel


def parse_classification_from_response(response_text: str) -> Optional[ConflictClassification]:
    """
    Parse classification from onboarding agent's JSON response.
    
    Expected format:
    {
      "handoff": true,
      "classification": {
        "resolvability": "...",
        "domain": "...",
        "nature": "...",
        "form": "...",
        "threat_level": "..."
      },
      "messages": [...]
    }
    """
    try:
        data = json.loads(response_text)
        
        if not data.get("handoff"):
            # Not ready for handoff yet
            return None
        
        classification_data = data.get("classification")
        if not classification_data:
            raise ValueError("Missing classification in handoff response")
        
        # Parse enums
        classification = ConflictClassification(
            resolvability=Resolvability(classification_data["resolvability"]),
            domain=Domain(classification_data["domain"]),
            nature=Nature(classification_data["nature"]),
            form=Form(classification_data["form"]),
            threat_level=ThreatLevel(classification_data["threat_level"]),
            confidence=classification_data.get("confidence", 1.0),
            reasoning=classification_data.get("reasoning"),
        )
        
        return classification
        
    except json.JSONDecodeError:
        print(f"Failed to parse JSON from response: {response_text[:200]}")
        return None
    except (KeyError, ValueError) as e:
        print(f"Invalid classification format: {e}")
        return None


def validate_classification(classification: ConflictClassification) -> bool:
    """Validate classification makes sense."""
    # Basic validation
    if classification.confidence < 0.5:
        print(f"Warning: Low confidence classification ({classification.confidence})")
        return False
    
    # Could add more validation logic here
    # e.g., certain combinations don't make sense
    
    return True

