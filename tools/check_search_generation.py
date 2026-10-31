"""Independent tiny-domain tensor-label/event-trace audit of the public generator."""

from dataclasses import replace
import hashlib
import itertools
import json
import math

from q3hash import BasisEncoding, GenerationReport, SearchConstraints, generate_encodings


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def encoding_value(logical, physical, mapping):
    # This is the published wire formula, independent of production serialization.
    return {"schema": "q3hash.basis-encoding", "schema_version": 1, "kind": "basis-injection",
            "logical_dimensions": list(logical), "physical_dimensions": list(physical),
            "physical_basis_indices": list(mapping)}


def tensor_trace(logical, constraints, seeds):
    """Materialise only tiny reference domains, then interpret budgets separately."""
    alphabet, maximum = constraints.allowed_dimensions, constraints.max_registers
    require(sum(len(alphabet) ** r for r in range(1, maximum + 1)) <= 128,
            "Independent oracle only accepts tiny declared domains")
    events = []
    for index, seed in enumerate(seeds):
        events.append(("mapping", seed.physical_dimensions, seed.physical_basis_indices,
                       "seed", index, None))
    tuples = [p for length in range(1, maximum + 1)
              for p in itertools.product(alphabet, repeat=length)]
    tuples.sort(key=lambda p: (len(p), p))
    for physical in tuples:
        size = math.prod(physical)
        rejection = ("physical-size-limit" if size > constraints.max_physical_size else
                     "insufficient-capacity" if size < math.prod(logical) else None)
        events.append(("dimension", rejection))
        if rejection is not None:
            continue
        labels = list(itertools.product(*(range(d) for d in physical)))
        indices = {label: index for index, label in enumerate(labels)}
        for family in constraints.mapping_families:
            if family == "flat-prefix":
                mapping = tuple(indices[label] for label in labels[:math.prod(logical)])
                events.append(("mapping", physical, mapping, family, None, None))
                continue
            if len(physical) < len(logical):
                events.append(("unavailable",))
                continue
            # Boundary masks and actual tensor labels replace production strides/cuts.
            cuts_values = sorted(tuple(i + 1 for i, selected in enumerate(mask) if selected)
                for mask in itertools.product((False, True), repeat=len(physical) - 1)
                if sum(mask) == len(logical) - 1)
            for cuts in cuts_values:
                bounds = (0, *cuts, len(physical))
                blocks = [list(itertools.product(*(range(d) for d in physical[start:end])))
                          for start, end in zip(bounds, bounds[1:])]
                if any(len(states) < dimension for states, dimension in zip(blocks, logical)):
                    events.append(("mapping", physical, None, family, None, cuts))
                    continue
                images = []
                for label in itertools.product(*(range(d) for d in logical)):
                    physical_label = tuple(value for block, digit in zip(blocks, label)
                                           for value in block[digit])
                    images.append(indices[physical_label])
                events.append(("mapping", physical, tuple(images), family, None, cuts))
    return events


def oracle(logical, constraints, seeds):
    events = tensor_trace(logical, constraints, seeds)
    result = {"candidates": [], "completion": "exhausted", "stop_reason": None,
              "dimension_tuples_seen": 0, "mapping_attempts": 0, "emitted_candidates": 0,
              "duplicate_mappings": 0, "dimension_rejections": {
                  "insufficient-capacity": 0, "physical-size-limit": 0},
              "partition_rejections": 0, "family_unavailable": 0}
    seen = set()

    def stop(reason):
        result.update(completion="truncated", stop_reason=reason)
        return result

    for event in events:
        if event[0] == "dimension":
            if result["dimension_tuples_seen"] == constraints.max_dimension_tuples:
                return stop("dimension-budget")
            result["dimension_tuples_seen"] += 1
            if event[1] is not None:
                result["dimension_rejections"][event[1]] += 1
        elif event[0] == "unavailable":
            result["family_unavailable"] += 1
        else:
            if result["mapping_attempts"] == constraints.max_mapping_attempts:
                return stop("mapping-budget")
            result["mapping_attempts"] += 1
            _, physical, mapping, origin, seed_index, cuts = event
            if mapping is None:
                result["partition_rejections"] += 1
                continue
            identity = (physical, mapping)
            if identity in seen:
                result["duplicate_mappings"] += 1
                continue
            if result["emitted_candidates"] == constraints.max_candidates:
                return stop("candidate-budget")
            value = encoding_value(logical, physical, mapping)
            identifier = hashlib.sha256(json.dumps(value, sort_keys=True,
                                        separators=(",", ":")).encode()).hexdigest()
            result["candidates"].append({"encoding": value, "candidate_id": identifier,
                "origin": origin, "seed_index": seed_index,
                "block_cuts": None if cuts is None else list(cuts)})
            seen.add(identity)
            result["emitted_candidates"] += 1
    return result


def audit():
    count = 0
    logical_values = ((2,), (3,), (4,), (2, 2), (2, 3), (3, 2), (2, 2, 2))
    family_values = (("flat-prefix",), ("register-prefix",), ("flat-prefix", "register-prefix"))
    for logical, alphabet, families in itertools.product(logical_values, ((2, 3), (2, 3, 4)), family_values):
        base = SearchConstraints(allowed_dimensions=alphabet, max_registers=3,
                                 max_physical_size=16, mapping_families=families)
        physical = next(p for length in range(1, 4) for p in itertools.product(alphabet, repeat=length)
                        if math.prod(logical) <= math.prod(p) <= 16)
        images = tuple(range(1, math.prod(logical))) + (0,)
        seed = BasisEncoding(logical, physical, images)
        for seeds, update in itertools.product(((), (seed,), (seed, seed)),
                ({}, {"max_dimension_tuples": 3}, {"max_mapping_attempts": 3}, {"max_candidates": 2})):
            constraints = replace(base, **update)
            expected = oracle(logical, constraints, seeds)
            report = generate_encodings(logical, constraints, seed_encodings=seeds)
            actual = report.to_dict()
            require({key: actual[key] for key in expected} == expected,
                    f"Independent generation mismatch: {logical}, {alphabet}, {families}, {len(seeds)}, {update}")
            # Decode replay is checked without importing any private production helper.
            require(GenerationReport.from_json(report.to_json()) == report, "Canonical report replay failed")
            count += 1
    return count


def main():
    count = audit()
    print(f"Independent tensor-label/event-trace generation audit: {count} cases passed")
    print("Evidence: bounded map enumeration, provenance, accounting and canonical replay; no circuit synthesis.")


if __name__ == "__main__":
    main()
