from enum import Enum

class AgentType(str, Enum):
    SUPPORTING = "supporting"
    SUPERVISOR = "supervisor"

class AgentRole(str, Enum):
    # Supervisor
    APPLICATION_SECURITY_SUPERVISOR = "application_security_supervisor"
    GOVERNANCE_RISK_COMPLIANCE_SUPERVISOR = "governance_risk_compliance_supervisor"
    DETECTION_INCIDENT_RESPONSE_SUPERVISOR = "detection_incident_response_supervisor"
    OFFENSIVE_SECURITY_SUPERVISOR = "offensive_security_supervisor"
    VULNERABILITY_MANAGEMENT_SUPERVISOR = "vulnerability_management_supervisor"
    CUSTOM_SUPERVISOR = "custom_supervisor"
    # Architect
    APPLICATION_SECURITY_ARCHITECT = "application_security_architect"
    DETECTION_INCIDENT_RESPONSE_ARCHITECT = "detection_incident_response_architect"
    SECURITY_ENGINEERING_ARCHITECT = "security_engineering_architect"
    # Engineer
    APPLICATION_SECURITY_ENGINEER = "application_security_engineer"
    GOVERNANCE_RISK_COMPLIANCE_ENGINEER = "governance_risk_compliance_engineer"
    DETECTION_INCIDENT_RESPONSE_ENGINEER = "detection_incident_response_engineer"
    OFFENSIVE_SECURITY_ENGINEER = "offensive_security_engineer"
    VULNERABILITY_MANAGEMENT_ENGINEER = "vulnerability_management_engineer"
    # Analyst
    APPLICATION_SECURITY_ANALYST = "application_security_analyst"
    GOVERNANCE_RISK_COMPLIANCE_ANALYST = "governance_risk_compliance_analyst"
    DETECTION_INCIDENT_RESPONSE_ANALYST = "detection_incident_response_analyst"
    OFFENSIVE_SECURITY_ANALYST = "offensive_security_analyst"
    VULNERABILITY_MANAGEMENT_ANALYST = "vulnerability_management_analyst"
    # Custom
    CUSTOM_SUPPORTING_AGENT = "custom_supporting_agent"