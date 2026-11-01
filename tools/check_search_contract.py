"""Audit tiny v0.4 contract vectors; this is not a production search engine."""

import itertools
import json
import math
from pathlib import Path

from q3hash import BasisEncoding, logical_from_source, verify_equivalence


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def block_map(logical, physical, cuts):
    boundaries = (0, *cuts, len(physical))
    capacities = tuple(math.prod(physical[a:b])
                       for a, b in zip(boundaries, boundaries[1:]))
    if any(a > b for a, b in zip(logical, capacities)):
        return None
    result = []
    for label in itertools.product(*(range(d) for d in logical)):
        index = 0
        for digit, capacity in zip(label, capacities):
            index = index * capacity + digit
        result.append(index)
    return tuple(result)


def tiny_generation(case, **limits):
    """An intentionally tiny Cartesian/label oracle, with no production helpers."""
    alphabet = case["allowed_dimensions"]
    registers = case["max_registers"]
    require(sum(len(alphabet) ** r for r in range(1, registers + 1)) <= 1024,
            "The reference-vector oracle is restricted to tiny domains")
    logical = tuple(case["logical_dimensions"])
    size = math.prod(logical)
    counters = dict(dimension_tuples_seen=0, mapping_attempts=0,
                    duplicate_mappings=0, insufficient_capacity=0,
                    physical_size_limit=0, block_capacity=0, family_unavailable=0)
    candidates, seen = [], set()

    def result(reason=None):
        return {"candidates": candidates, "counts": counters,
                "completion": "truncated" if reason else "exhausted",
                "stop_reason": reason}

    for count in range(1, registers + 1):
        for physical in itertools.product(alphabet, repeat=count):
            if counters["dimension_tuples_seen"] >= limits.get("max_dimension_tuples", 4096):
                return result("dimension-budget")
            counters["dimension_tuples_seen"] += 1
            capacity = math.prod(physical)
            if capacity > case["max_physical_size"]:
                counters["physical_size_limit"] += 1
                continue
            if capacity < size:
                counters["insufficient_capacity"] += 1
                continue
            for family in case["mapping_families"]:
                if family == "register-prefix" and count < len(logical):
                    counters["family_unavailable"] += 1
                    continue
                patterns = (None,) if family == "flat-prefix" else itertools.combinations(
                    range(1, count), len(logical) - 1)
                for cuts in patterns:
                    if counters["mapping_attempts"] >= limits.get("max_mapping_attempts", 16384):
                        return result("mapping-budget")
                    counters["mapping_attempts"] += 1
                    mapping = tuple(range(size)) if cuts is None else block_map(logical, physical, cuts)
                    if mapping is None:
                        counters["block_capacity"] += 1
                        continue
                    require(len(set(mapping)) == size and all(0 <= v < capacity for v in mapping),
                            "Reference map must be injective and in range")
                    identity = (physical, mapping)
                    if identity in seen:
                        counters["duplicate_mappings"] += 1
                        continue
                    if len(candidates) >= limits.get("max_candidates", 256):
                        return result("candidate-budget")
                    seen.add(identity)
                    candidates.append({"physical_dimensions": list(physical), "mapping": list(mapping)})
    return result()


def resources(ir, logical_size):
    # Explicit instruction dependency sets; independent of future production code.
    last = [0] * len(ir.registers)
    two = 0
    for operation in ir.operations:
        axes = [operation.target]
        if operation.control is not None:
            axes.append(operation.control)
            two += 1
        layer = 1 + max(last[axis] for axis in axes)
        for axis in axes:
            last[axis] = layer
    return [len(ir.registers), max(ir.dimensions), math.prod(ir.dimensions) - logical_size,
            len(ir.operations), two, max(last)]


def front(rows, objectives):
    return [i for i, row in enumerate(rows) if not any(
        all(other[k] <= row[k] for k in objectives) and
        any(other[k] < row[k] for k in objectives) for other in rows)]


def main():
    path = Path(__file__).resolve().parents[1] / "benchmarks/encoding-search-v1.json"
    vectors = json.loads(path.read_text(encoding="utf-8"))
    require(vectors["schema"] == "q3hash.search-contract-vectors" and
            type(vectors["schema_version"]) is int and vectors["schema_version"] == 1,
            "Unknown contract-vector schema")
    checks = 0
    for case in vectors["generation_cases"]:
        actual = tiny_generation(case)
        require(actual["candidates"] == case["expected_candidates"], case["id"] + " ordering")
        require(actual["counts"] == case["expected_counts"], case["id"] + " accounting")
        require(actual["completion"] == "exhausted", case["id"] + " exhaustion")
        checks += 1
        for boundary in case["budget_cases"]:
            actual = tiny_generation(case, **boundary["limits"])
            for field in ("completion", "stop_reason"):
                require(actual[field] == boundary[field], case["id"] + " " + field)
            for field in ("dimension_tuples_seen", "mapping_attempts"):
                require(actual["counts"][field] == boundary[field], case["id"] + " " + field)
            require(len(actual["candidates"]) == boundary["candidate_count"], "Boundary prefix size")
            require(actual["candidates"] == case["expected_candidates"][:boundary["candidate_count"]],
                    "Boundary must retain the canonical prefix")
            checks += 1
    for case in vectors["mapping_cases"]:
        mapping = block_map(tuple(case["logical_dimensions"]), tuple(case["physical_dimensions"]),
                            tuple(case["cuts"]))
        require(mapping is None if "rejection" in case else list(mapping) == case["mapping"],
                case["id"])
        checks += 1
    for case in vectors["operator_cases"]:
        logical = logical_from_source(case["logical"])
        physical = logical_from_source(case["physical"]).ir
        encoding = BasisEncoding(logical.dimensions, physical.dimensions, tuple(case["mapping"]))
        report = verify_equivalence(logical, physical, encoding,
                                    max_dimension=case.get("max_dimension", 64))
        require(report.status == case["expected"], case["id"] + ": " + report.reason)
        if "resources" in case:
            require(resources(physical, logical.state_size) == case["resources"], case["id"] + " cost")
        checks += 1
    for case in vectors["resource_cases"]:
        require(resources(logical_from_source(case["source"]).ir, case["logical_size"]) ==
                case["resources"], case["id"])
        checks += 1
    for case in vectors["pareto_cases"]:
        require(front(case["rows"], case["objective_indices"]) == case["front_indices"], case["id"])
        checks += 1
    print(f"v0.4 contract vectors: {checks} cases passed")
    print("Reference-vector audit; production aggregate evaluation has its own audit; CLI remains pending.")


if __name__ == "__main__":
    main()
