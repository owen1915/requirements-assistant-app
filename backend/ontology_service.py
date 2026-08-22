from pathlib import Path
from datetime import datetime

from rdflib import Graph, Namespace, Literal, RDF, RDFS, XSD, URIRef
import pyshacl

IR = Namespace("http://sie.arizona.edu/ontology/incose-req#")

_SEVERITY_MAP = {
    "low": IR.SeverityLow,
    "medium": IR.SeverityMedium,
    "high": IR.SeverityHigh,
    "critical": IR.SeverityCritical,
}

# Coverage query: for each characteristic, count total rules and triggered rules
_COVERAGE_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?charId ?charLabel
       (COUNT(DISTINCT ?rule) AS ?rulesTotal)
       (COUNT(DISTINCT ?triggeredRule) AS ?rulesTriggered)
WHERE {
    ?char ir:hasCharacteristicId ?charId ;
          rdfs:label ?charLabel .
    ?rule ir:testsCharacteristic ?char .
    OPTIONAL {
        ?triggeredRule ir:testsCharacteristic ?char .
        ?violation ir:violatesRule ?triggeredRule .
        ?result ir:includesViolation ?violation .
        ?assessment a ir:Assessment ;
                    ir:hasResult ?result .
    }
}
GROUP BY ?charId ?charLabel
ORDER BY ?charId
"""

# Rule coverage: which rules were triggered vs. not
_RULE_COVERAGE_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>

SELECT (COUNT(DISTINCT ?rule) AS ?total)
       (COUNT(DISTINCT ?triggeredRule) AS ?triggered)
WHERE {
    ?rule a ir:Rule .
    OPTIONAL {
        ?triggeredRule a ir:Rule .
        ?violation ir:violatesRule ?triggeredRule .
        ?result ir:includesViolation ?violation .
        ?assessment a ir:Assessment ;
                    ir:hasResult ?result .
    }
}
"""

# Quality profile per requirement
_QUALITY_PROFILE_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?reqId ?charId ?charLabel (COUNT(DISTINCT ?violation) AS ?violationCount)
WHERE {
    ?req a ir:Requirement ;
         ir:hasRequirementId ?reqId ;
         ir:memberOfSet ?set .
    ?char ir:hasCharacteristicId ?charId ;
          rdfs:label ?charLabel .
    ?rule ir:testsCharacteristic ?char .
    OPTIONAL {
        ?violation ir:violatesRule ?rule ;
                   ir:inheresInRequirement ?req .
        ?result ir:includesViolation ?violation .
        ?assessment a ir:Assessment ;
                    ir:hasResult ?result .
    }
}
GROUP BY ?reqId ?charId ?charLabel
ORDER BY ?reqId ?charId
"""

# Severity distribution via CQ-IR05 pattern
_SEVERITY_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?severityLabel (COUNT(?violation) AS ?violCount)
WHERE {
    ?assessment a ir:Assessment ;
                ir:hasResult ?result .
    ?result ir:includesViolation ?violation .
    ?violation ir:hasSeverityRating ?severity .
    ?severity rdfs:label ?severityLabel ;
              ir:hasOrdinalRank ?rank .
}
GROUP BY ?severityLabel ?rank
ORDER BY ?rank
"""


def _rule_iri(rule_id_str):
    """Convert 'R7' to incose-req:R07, 'R12' to incose-req:R12."""
    num = rule_id_str.lstrip("Rr")
    return IR[f"R{int(num):02d}"]


class OntologyService:
    def __init__(self, tbox_path, abox_path, shapes_path):
        self._def_graph = Graph()
        self._def_graph.parse(tbox_path, format="turtle")
        self._def_graph.parse(abox_path, format="turtle")
        self._shapes_graph = Graph()
        self._shapes_graph.parse(shapes_path, format="turtle")

    def mint_assessment_rdf(self, session_id, analysis_json):
        g = Graph()
        g.bind("ir", IR)

        set_uri = IR[f"ReqSet_{session_id}"]
        g.add((set_uri, RDF.type, IR.RequirementSet))

        assessment_uri = IR[f"Assessment_{session_id}"]
        g.add((assessment_uri, RDF.type, IR.Assessment))
        g.add((assessment_uri, IR.assessesSet, set_uri))
        g.add((assessment_uri, IR.hasAssessor, Literal("Requirements-Assistant-AI")))
        g.add((assessment_uri, IR.hasAssessmentDate,
               Literal(datetime.utcnow().isoformat(), datatype=XSD.dateTime)))

        result_uri = IR[f"Result_{session_id}"]
        g.add((result_uri, RDF.type, IR.AssessmentResult))
        g.add((assessment_uri, IR.hasResult, result_uri))

        for req in analysis_json.get("requirements", []):
            req_id = req.get("req_id", "UNKNOWN")
            safe_req_id = req_id.replace(" ", "_")
            req_uri = IR[f"Req_{session_id}_{safe_req_id}"]
            g.add((req_uri, RDF.type, IR.Requirement))
            g.add((req_uri, IR.hasRequirementId, Literal(req_id)))
            g.add((req_uri, IR.hasStatementText,
                   Literal(req.get("original_text", ""))))
            g.add((req_uri, IR.memberOfSet, set_uri))

            for v in req.get("violations", []):
                vid = v.get("violation_id", "v")
                safe_vid = vid.replace(" ", "_").replace("-", "_")
                v_uri = IR[f"Violation_{session_id}_{safe_vid}"]
                g.add((v_uri, RDF.type, IR.Violation))

                rule_id = v.get("rule_id", "")
                g.add((v_uri, IR.violatesRule, _rule_iri(rule_id)))
                g.add((v_uri, IR.inheresInRequirement, req_uri))

                severity = v.get("severity", "medium").lower()
                sev_uri = _SEVERITY_MAP.get(severity, IR.SeverityMedium)
                g.add((v_uri, IR.hasSeverityRating, sev_uri))

                affected = v.get("affected_text", "")
                if affected:
                    g.add((v_uri, IR.hasAffectedText, Literal(affected)))

                # Direct characteristic links from LLM output (characteristic_ids)
                # Complements the rule→characteristic inference path in the TBox.
                for char_id in v.get("characteristic_ids", []):
                    char_id_str = str(char_id).strip().upper()
                    # Normalise C3 → C03 style IRI if needed
                    try:
                        num = int(char_id_str.lstrip("C"))
                        char_iri = IR[f"C{num:02d}"]
                        g.add((v_uri, IR.degradesCharacteristic, char_iri))
                    except (ValueError, AttributeError):
                        pass

                g.add((result_uri, IR.includesViolation, v_uri))

        # Merge with definitional graph for querying
        merged = self._def_graph + g
        return merged

    def validate_assessment(self, assessment_graph):
        conforms, results_graph, results_text = pyshacl.validate(
            assessment_graph,
            shacl_graph=self._shapes_graph,
            inference="none",
        )
        violations = []
        if not conforms:
            SH = Namespace("http://www.w3.org/ns/shacl#")
            for result in results_graph.subjects(RDF.type, SH.ValidationResult):
                detail = {}
                for p, label in [
                    (SH.focusNode, "focus_node"),
                    (SH.resultPath, "path"),
                    (SH.resultMessage, "message"),
                    (SH.resultSeverity, "severity"),
                ]:
                    val = results_graph.value(result, p)
                    if val is not None:
                        detail[label] = str(val)
                violations.append(detail)
        return conforms, violations

    def compute_coverage(self, assessment_graph):
        char_rows = list(assessment_graph.query(_COVERAGE_QUERY))
        characteristic_coverage = []
        for row in char_rows:
            total = int(row.rulesTotal)
            triggered = int(row.rulesTriggered)
            characteristic_coverage.append({
                "char_id": str(row.charId),
                "char_label": str(row.charLabel),
                "rules_total": total,
                "rules_triggered": triggered,
                "covered": triggered > 0,
            })

        rule_row = list(assessment_graph.query(_RULE_COVERAGE_QUERY))
        total_rules = int(rule_row[0].total) if rule_row else 0
        triggered_rules = int(rule_row[0].triggered) if rule_row else 0

        return {
            "characteristic_coverage": characteristic_coverage,
            "rule_coverage": {
                "total": total_rules,
                "triggered": triggered_rules,
                "untriggered": total_rules - triggered_rules,
            },
        }

    def compute_quality_profile(self, assessment_graph):
        rows = list(assessment_graph.query(_QUALITY_PROFILE_QUERY))
        per_req = {}
        for row in rows:
            req_id = str(row.reqId)
            if req_id not in per_req:
                per_req[req_id] = []
            count = int(row.violationCount)
            per_req[req_id].append({
                "char_id": str(row.charId),
                "char_label": str(row.charLabel),
                "violation_count": count,
                "status": "FAIL" if count > 0 else "PASS",
            })

        # Aggregate across all requirements
        char_totals = {}
        for chars in per_req.values():
            for c in chars:
                cid = c["char_id"]
                if cid not in char_totals:
                    char_totals[cid] = {
                        "char_id": cid,
                        "char_label": c["char_label"],
                        "total_violations": 0,
                    }
                char_totals[cid]["total_violations"] += c["violation_count"]

        aggregate = []
        for cid in sorted(char_totals):
            entry = char_totals[cid]
            entry["status"] = "FAIL" if entry["total_violations"] > 0 else "PASS"
            aggregate.append(entry)

        return {
            "per_requirement": per_req,
            "aggregate": aggregate,
        }

    def compute_severity_distribution(self, assessment_graph):
        rows = list(assessment_graph.query(_SEVERITY_QUERY))
        dist = {}
        for row in rows:
            dist[str(row.severityLabel)] = int(row.violCount)
        # Fill in zeros for levels with no violations
        for label in ["Low", "Medium", "High", "Critical"]:
            dist.setdefault(label, 0)
        return dist
