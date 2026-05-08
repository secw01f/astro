from enum import Enum

class AttackVector(str, Enum):
    NETWORK = "N"
    ADJACENT = "A"
    LOCAL = "L"
    PHYSICAL = "P"

class AttackComplexity(str, Enum):
    LOW = "L"
    HIGH = "H"

class AttackRequirements(str, Enum):
    NONE = "N"
    PRESENT = "P"

class PrivilegesRequired(str, Enum):
    NONE = "N"
    LOW = "L"
    HIGH = "H"

class UserInteraction(str, Enum):
    NONE = "N"
    PASSIVE = "P"
    ACTIVE = "A"

class Impact(str, Enum):
    HIGH = "H"
    LOW = "L"
    NONE = "N"

class ExploitMaturity(str, Enum):
    NOT_DEFINED = "X"
    ATTACKED = "A"
    PROOF_OF_CONCEPT = "P"
    UNREPORTED = "U"

class Requirement(str, Enum):
    NOT_DEFINED = "X"
    HIGH = "H"
    MEDIUM = "M"
    LOW = "L"

class ModifiedAttackVector(str, Enum):
    NOT_DEFINED = "X"
    NETWORK = "N"
    ADJACENT = "A"
    LOCAL = "L"
    PHYSICAL = "P"

class ModifiedAttackComplexity(str, Enum):
    NOT_DEFINED = "X"
    LOW = "L"
    HIGH = "H"

class ModifiedAttackRequirements(str, Enum):
    NOT_DEFINED = "X"
    NONE = "N"
    PRESENT = "P"

class ModifiedPrivilegesRequired(str, Enum):
    NOT_DEFINED = "X"
    NONE = "N"
    LOW = "L"
    HIGH = "H"

class ModifiedUserInteraction(str, Enum):
    NOT_DEFINED = "X"
    NONE = "N"
    PASSIVE = "P"
    ACTIVE = "A"

class ModifiedImpact(str, Enum):
    NOT_DEFINED = "X"
    HIGH = "H"
    LOW = "L"
    NONE = "N"

class Safety(str, Enum):
    NOT_DEFINED = "X"
    NEGLIGIBLE = "N"
    PRESENT = "P"

class Automatable(str, Enum):
    NOT_DEFINED = "X"
    NO = "N"
    YES = "Y"

class Recovery(str, Enum):
    NOT_DEFINED = "X"
    AUTOMATIC = "A"
    USER = "U"
    IRRECOVERABLE = "I"

class ValueDensity(str, Enum):
    NOT_DEFINED = "X"
    DIFFUSE = "D"
    CONCENTRATED = "C"

class ResponseEffort(str, Enum):
    NOT_DEFINED = "X"
    LOW = "L"
    MODERATE = "M"
    HIGH = "H"

class ProviderUrgency(str, Enum):
    NOT_DEFINED = "X"
    CLEAR = "Clear"
    GREEN = "Green"
    AMBER = "Amber"
    RED = "Red"

class CVSSV3UserInteraction(str, Enum):
    NONE = "N"
    REQUIRED = "R"

class CVSSV3Scope(str, Enum):
    UNCHANGED = "U"
    CHANGED = "C"

class CVSSV3Impact(str, Enum):
    NONE = "N"
    LOW = "L"
    HIGH = "H"

class CVSSV3ExploitCodeMaturity(str, Enum):
    NOT_DEFINED = "X"
    UNPROVEN = "U"
    PROOF_OF_CONCEPT = "P"
    FUNCTIONAL = "F"
    HIGH = "H"

class CVSSV3RemediationLevel(str, Enum):
    NOT_DEFINED = "X"
    OFFICIAL_FIX = "O"
    TEMPORARY_FIX = "T"
    WORKAROUND = "W"
    UNAVAILABLE = "U"

class CVSSV3ReportConfidence(str, Enum):
    NOT_DEFINED = "X"
    UNKNOWN = "U"
    REASONABLE = "R"
    CONFIRMED = "C"

class CVSSV3ModifiedUserInteraction(str, Enum):
    NOT_DEFINED = "X"
    NONE = "N"
    REQUIRED = "R"

class CVSSV3ModifiedScope(str, Enum):
    NOT_DEFINED = "X"
    UNCHANGED = "U"
    CHANGED = "C"