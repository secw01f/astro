import httpx
from cvss import CVSS3, CVSS4
from pydantic import BaseModel

from lib.tool import create_tool_registry
from src.asm.enums import (
    AttackComplexity,
    AttackRequirements,
    AttackVector,
    Automatable,
    CVSSV3ExploitCodeMaturity,
    CVSSV3ModifiedScope,
    CVSSV3ModifiedUserInteraction,
    CVSSV3RemediationLevel,
    CVSSV3ReportConfidence,
    CVSSV3Scope,
    CVSSV3UserInteraction,
    ExploitMaturity,
    Impact,
    ModifiedAttackComplexity,
    ModifiedAttackRequirements,
    ModifiedAttackVector,
    ModifiedImpact,
    ModifiedPrivilegesRequired,
    ModifiedUserInteraction,
    PrivilegesRequired,
    ProviderUrgency,
    Recovery,
    Requirement,
    ResponseEffort,
    Safety,
    UserInteraction,
    ValueDensity,
)

Registry, tool = create_tool_registry("asm")

class NVDInput(BaseModel):
    cve: str

@tool(name="nvd", description="Search NVD for vulnerability data", capabilities=["vulnerability_management"], version="1.0")
async def nvd(input: NVDInput) -> dict:
    params = {"cveId": input.cve}
    async with httpx.AsyncClient(base_url="https://services.nvd.nist.gov/rest/json/cves/2.0") as client:
        response = await client.get("", params=params)
    return response.json()


class CVSSV4BaseMetrics(BaseModel):
    attack_vector: AttackVector
    attack_complexity: AttackComplexity
    attack_requirements: AttackRequirements
    privileges_required: PrivilegesRequired
    user_interaction: UserInteraction
    vulnerable_confidentiality: Impact
    vulnerable_integrity: Impact
    vulnerable_availability: Impact
    subsequent_confidentiality: Impact
    subsequent_integrity: Impact
    subsequent_availability: Impact

class CVSSV4ThreatMetrics(BaseModel):
    exploit_maturity: ExploitMaturity = ExploitMaturity.NOT_DEFINED

class CVSSV4EnvironmentalMetrics(BaseModel):
    confidentiality_requirement: Requirement = Requirement.NOT_DEFINED
    integrity_requirement: Requirement = Requirement.NOT_DEFINED
    availability_requirement: Requirement = Requirement.NOT_DEFINED
    modified_attack_vector: ModifiedAttackVector = ModifiedAttackVector.NOT_DEFINED
    modified_attack_complexity: ModifiedAttackComplexity = ModifiedAttackComplexity.NOT_DEFINED
    modified_attack_requirements: ModifiedAttackRequirements = ModifiedAttackRequirements.NOT_DEFINED
    modified_privileges_required: ModifiedPrivilegesRequired = ModifiedPrivilegesRequired.NOT_DEFINED
    modified_user_interaction: ModifiedUserInteraction = ModifiedUserInteraction.NOT_DEFINED
    modified_vulnerable_confidentiality: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_vulnerable_integrity: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_vulnerable_availability: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_subsequent_confidentiality: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_subsequent_integrity: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_subsequent_availability: ModifiedImpact = ModifiedImpact.NOT_DEFINED

class CVSSV4SupplementalMetrics(BaseModel):
    safety: Safety = Safety.NOT_DEFINED
    automatable: Automatable = Automatable.NOT_DEFINED
    recovery: Recovery = Recovery.NOT_DEFINED
    value_density: ValueDensity = ValueDensity.NOT_DEFINED
    response_effort: ResponseEffort = ResponseEffort.NOT_DEFINED
    provider_urgency: ProviderUrgency = ProviderUrgency.NOT_DEFINED

class CVSSV4Input(BaseModel):
    base: CVSSV4BaseMetrics
    threat: CVSSV4ThreatMetrics = CVSSV4ThreatMetrics()
    environmental: CVSSV4EnvironmentalMetrics = CVSSV4EnvironmentalMetrics()
    supplemental: CVSSV4SupplementalMetrics = CVSSV4SupplementalMetrics()

@tool(name="cvssv4", description="Build a CVSS v4 vector payload", capabilities=["vulnerability_management"], version="1.0")
async def cvssv4(input: CVSSV4Input) -> dict:
    vector = (
        "CVSS:4.0"
        f"/AV:{input.base.attack_vector.value}"
        f"/AC:{input.base.attack_complexity.value}"
        f"/AT:{input.base.attack_requirements.value}"
        f"/PR:{input.base.privileges_required.value}"
        f"/UI:{input.base.user_interaction.value}"
        f"/VC:{input.base.vulnerable_confidentiality.value}"
        f"/VI:{input.base.vulnerable_integrity.value}"
        f"/VA:{input.base.vulnerable_availability.value}"
        f"/SC:{input.base.subsequent_confidentiality.value}"
        f"/SI:{input.base.subsequent_integrity.value}"
        f"/SA:{input.base.subsequent_availability.value}"
        f"/E:{input.threat.exploit_maturity.value}"
        f"/CR:{input.environmental.confidentiality_requirement.value}"
        f"/IR:{input.environmental.integrity_requirement.value}"
        f"/AR:{input.environmental.availability_requirement.value}"
        f"/MAV:{input.environmental.modified_attack_vector.value}"
        f"/MAC:{input.environmental.modified_attack_complexity.value}"
        f"/MAT:{input.environmental.modified_attack_requirements.value}"
        f"/MPR:{input.environmental.modified_privileges_required.value}"
        f"/MUI:{input.environmental.modified_user_interaction.value}"
        f"/MVC:{input.environmental.modified_vulnerable_confidentiality.value}"
        f"/MVI:{input.environmental.modified_vulnerable_integrity.value}"
        f"/MVA:{input.environmental.modified_vulnerable_availability.value}"
        f"/MSC:{input.environmental.modified_subsequent_confidentiality.value}"
        f"/MSI:{input.environmental.modified_subsequent_integrity.value}"
        f"/MSA:{input.environmental.modified_subsequent_availability.value}"
        f"/S:{input.supplemental.safety.value}"
        f"/AU:{input.supplemental.automatable.value}"
        f"/R:{input.supplemental.recovery.value}"
        f"/V:{input.supplemental.value_density.value}"
        f"/RE:{input.supplemental.response_effort.value}"
        f"/U:{input.supplemental.provider_urgency.value}"
    )
    
    parsed = CVSS4(vector)
    score = float(parsed.scores()[0])
    severity = parsed.severities()[0]
    normalized_vector = parsed.clean_vector()

    return {
        "version": "4.0",
        "vector": normalized_vector,
        "score": score,
        "severity": severity,
        "base_metrics": input.base.model_dump(),
        "threat_metrics": input.threat.model_dump(),
        "environmental_metrics": input.environmental.model_dump(),
        "supplemental_metrics": input.supplemental.model_dump(),
    }


class CVSSV3BaseMetrics(BaseModel):
    attack_vector: AttackVector
    attack_complexity: AttackComplexity
    privileges_required: PrivilegesRequired
    user_interaction: CVSSV3UserInteraction
    scope: CVSSV3Scope
    confidentiality: Impact
    integrity: Impact
    availability: Impact

class CVSSV3TemporalMetrics(BaseModel):
    exploit_code_maturity: CVSSV3ExploitCodeMaturity = CVSSV3ExploitCodeMaturity.NOT_DEFINED
    remediation_level: CVSSV3RemediationLevel = CVSSV3RemediationLevel.NOT_DEFINED
    report_confidence: CVSSV3ReportConfidence = CVSSV3ReportConfidence.NOT_DEFINED

class CVSSV3EnvironmentalMetrics(BaseModel):
    confidentiality_requirement: Requirement = Requirement.NOT_DEFINED
    integrity_requirement: Requirement = Requirement.NOT_DEFINED
    availability_requirement: Requirement = Requirement.NOT_DEFINED
    modified_attack_vector: ModifiedAttackVector = ModifiedAttackVector.NOT_DEFINED
    modified_attack_complexity: ModifiedAttackComplexity = ModifiedAttackComplexity.NOT_DEFINED
    modified_privileges_required: ModifiedPrivilegesRequired = ModifiedPrivilegesRequired.NOT_DEFINED
    modified_user_interaction: CVSSV3ModifiedUserInteraction = CVSSV3ModifiedUserInteraction.NOT_DEFINED
    modified_scope: CVSSV3ModifiedScope = CVSSV3ModifiedScope.NOT_DEFINED
    modified_confidentiality: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_integrity: ModifiedImpact = ModifiedImpact.NOT_DEFINED
    modified_availability: ModifiedImpact = ModifiedImpact.NOT_DEFINED

class CVSSV3Input(BaseModel):
    base: CVSSV3BaseMetrics
    temporal: CVSSV3TemporalMetrics = CVSSV3TemporalMetrics()
    environmental: CVSSV3EnvironmentalMetrics = CVSSV3EnvironmentalMetrics()

@tool(name="cvssv3", description="Build and score a CVSS v3.1 vector payload", capabilities=["vulnerability_management"], version="1.0")
async def cvssv3(input: CVSSV3Input) -> dict:
    vector = (
        "CVSS:3.1"
        f"/AV:{input.base.attack_vector.value}"
        f"/AC:{input.base.attack_complexity.value}"
        f"/PR:{input.base.privileges_required.value}"
        f"/UI:{input.base.user_interaction.value}"
        f"/S:{input.base.scope.value}"
        f"/C:{input.base.confidentiality.value}"
        f"/I:{input.base.integrity.value}"
        f"/A:{input.base.availability.value}"
        f"/E:{input.temporal.exploit_code_maturity.value}"
        f"/RL:{input.temporal.remediation_level.value}"
        f"/RC:{input.temporal.report_confidence.value}"
        f"/CR:{input.environmental.confidentiality_requirement.value}"
        f"/IR:{input.environmental.integrity_requirement.value}"
        f"/AR:{input.environmental.availability_requirement.value}"
        f"/MAV:{input.environmental.modified_attack_vector.value}"
        f"/MAC:{input.environmental.modified_attack_complexity.value}"
        f"/MPR:{input.environmental.modified_privileges_required.value}"
        f"/MUI:{input.environmental.modified_user_interaction.value}"
        f"/MS:{input.environmental.modified_scope.value}"
        f"/MC:{input.environmental.modified_confidentiality.value}"
        f"/MI:{input.environmental.modified_integrity.value}"
        f"/MA:{input.environmental.modified_availability.value}"
    )

    parsed = CVSS3(vector)
    score = float(parsed.scores()[0])
    severity = parsed.severities()[0]
    normalized_vector = parsed.clean_vector()

    return {
        "version": "3.1",
        "vector": normalized_vector,
        "score": score,
        "severity": severity,
        "base_metrics": input.base.model_dump(),
        "temporal_metrics": input.temporal.model_dump(),
        "environmental_metrics": input.environmental.model_dump(),
    }