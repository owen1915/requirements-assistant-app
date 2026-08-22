from pathlib import Path
from rdflib import Graph, Namespace, Literal

IR = Namespace("http://sie.arizona.edu/ontology/incose-req#")
RDFS = Namespace("http://www.w3.org/2000/01/rdf-schema#")

_ALL_RULES_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?rule ?rule_id ?label ?description ?category ?category_label
       ?applicability ?applicability_label ?requires_dict
WHERE {
    ?rule a ir:Rule ;
          ir:hasRuleId ?rule_id ;
          rdfs:label ?label ;
          ir:belongsToCategory ?category ;
          ir:hasApplicability ?applicability ;
          ir:requiresProjectDictionary ?requires_dict .
    ?category rdfs:label ?category_label .
    ?applicability rdfs:label ?applicability_label .
    OPTIONAL { ?rule ir:hasShortDescription ?description . }
}
ORDER BY ?rule_id
"""

_RULE_CHARACTERISTICS_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?rule_id ?char_id ?char_label ?char_description
WHERE {
    ?rule a ir:Rule ;
          ir:hasRuleId ?rule_id ;
          ir:testsCharacteristic ?char .
    ?char ir:hasCharacteristicId ?char_id ;
          rdfs:label ?char_label .
    OPTIONAL { ?char ir:hasShortDescription ?char_description . }
}
ORDER BY ?rule_id ?char_id
"""

_ALL_CHARACTERISTICS_QUERY = """
PREFIX ir: <http://sie.arizona.edu/ontology/incose-req#>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?char_id ?label ?description ?type
WHERE {
    ?char ir:hasCharacteristicId ?char_id ;
          rdfs:label ?label .
    OPTIONAL { ?char ir:hasShortDescription ?description . }
    BIND(
        IF(EXISTS { ?char a ir:IndividualQualityCharacteristic }, "Individual",
        IF(EXISTS { ?char a ir:SetQualityCharacteristic }, "Set", "Unknown"))
        AS ?type
    )
}
ORDER BY ?char_id
"""


class OntologyLoader:
    def __init__(self, tbox_path, abox_path):
        self._graph = Graph()
        self._graph.parse(tbox_path, format="turtle")
        self._graph.parse(abox_path, format="turtle")
        self._rules_cache = None
        self._characteristics_cache = None
        # Derived index caches
        self._rules_by_id = None
        self._rules_by_char = None
        self._rules_by_category = None
        self._chars_by_id = None

    # ------------------------------------------------------------------
    # Primary accessors (cached)
    # ------------------------------------------------------------------

    def get_all_rules(self):
        if self._rules_cache is not None:
            return self._rules_cache

        # Build characteristic map per rule (with descriptions)
        char_map = {}
        for row in self._graph.query(_RULE_CHARACTERISTICS_QUERY):
            rid = str(row.rule_id)
            if rid not in char_map:
                char_map[rid] = []
            char_map[rid].append({
                "id": str(row.char_id),
                "label": str(row.char_label),
                "description": str(row.char_description) if row.char_description else "",
            })

        rules = []
        for row in self._graph.query(_ALL_RULES_QUERY):
            rid = str(row.rule_id)
            rules.append({
                "rule_id": rid,
                "label": str(row.label),
                "description": str(row.description) if row.description else "",
                "category": str(row.category_label),
                "applicability": str(row.applicability_label),
                "requires_project_dictionary": bool(row.requires_dict),
                "characteristics": char_map.get(rid, []),
            })

        self._rules_cache = rules
        self._rebuild_indexes()
        return rules

    def get_all_characteristics(self):
        if self._characteristics_cache is not None:
            return self._characteristics_cache

        chars = []
        for row in self._graph.query(_ALL_CHARACTERISTICS_QUERY):
            chars.append({
                "id": str(row.char_id),
                "label": str(row.label),
                "description": str(row.description) if row.description else "",
                "type": str(row.type),
            })

        self._characteristics_cache = chars
        self._rebuild_char_index()
        return chars

    # ------------------------------------------------------------------
    # Derived lookup methods (used by tool-use handlers)
    # ------------------------------------------------------------------

    def get_rule_by_id(self, rule_id: str):
        """Return full rule details for a single rule ID (e.g. 'R5')."""
        self._ensure_indexes()
        rule_id = rule_id.strip().upper()
        result = self._rules_by_id.get(rule_id)
        if result is None:
            return {"error": f"Rule '{rule_id}' not found. Valid IDs are R1-R42."}
        return result

    def get_rules_for_characteristic(self, char_id: str):
        """Return all rules that test a given characteristic ID (e.g. 'C3')."""
        self._ensure_indexes()
        char_id = char_id.strip().upper()
        rules = self._rules_by_char.get(char_id, [])
        if not rules:
            return {"error": f"No rules found for characteristic '{char_id}'. Valid IDs are C1-C15."}
        # Include characteristic info in the response
        char_info = self._chars_by_id.get(char_id, {})
        return {
            "characteristic": char_info,
            "rules": rules,
        }

    def get_rules_by_category(self, category: str):
        """Return all rules in a named category (case-insensitive)."""
        self._ensure_indexes()
        category_key = category.strip().lower()
        # Find matching category (case-insensitive)
        for cat_label, rules in self._rules_by_category.items():
            if cat_label.lower() == category_key:
                return {"category": cat_label, "rules": rules}
        # Partial match fallback
        matches = {k: v for k, v in self._rules_by_category.items()
                   if category_key in k.lower()}
        if matches:
            # Return the first match
            cat_label, rules = next(iter(matches.items()))
            return {"category": cat_label, "rules": rules}
        available = sorted(self._rules_by_category.keys())
        return {
            "error": f"Category '{category}' not found.",
            "available_categories": available,
        }

    def get_characteristic_by_id(self, char_id: str):
        """Return full details for a single characteristic (e.g. 'C3')."""
        self._ensure_indexes()
        char_id = char_id.strip().upper()
        result = self._chars_by_id.get(char_id)
        if result is None:
            return {"error": f"Characteristic '{char_id}' not found. Valid IDs are C1-C15."}
        return result

    def get_rules_by_applicability(self, level):
        return [r for r in self.get_all_rules() if r["applicability"] == level]

    def get_dictionary_dependent_rules(self):
        return [r for r in self.get_all_rules() if r["requires_project_dictionary"]]

    # ------------------------------------------------------------------
    # Internal index helpers
    # ------------------------------------------------------------------

    def _ensure_indexes(self):
        if self._rules_by_id is None:
            self.get_all_rules()
        if self._chars_by_id is None:
            self.get_all_characteristics()

    def _rebuild_indexes(self):
        self._rules_by_id = {r["rule_id"]: r for r in self._rules_cache}
        # Index by characteristic
        self._rules_by_char = {}
        for rule in self._rules_cache:
            for char in rule["characteristics"]:
                cid = char["id"]
                if cid not in self._rules_by_char:
                    self._rules_by_char[cid] = []
                self._rules_by_char[cid].append(rule)
        # Index by category
        self._rules_by_category = {}
        for rule in self._rules_cache:
            cat = rule["category"]
            if cat not in self._rules_by_category:
                self._rules_by_category[cat] = []
            self._rules_by_category[cat].append(rule)

    def _rebuild_char_index(self):
        self._chars_by_id = {c["id"]: c for c in self._characteristics_cache}
