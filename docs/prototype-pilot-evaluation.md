# Evaluate discovery on a new prototype

This protocol measures how well a saved scenario batch covers an independent set of operating conditions. It also records where a person had to translate measurements, supply missing information or change code. The evaluator runs offline using Python's standard library.

## Before starting the project

Have a person familiar with the device list the conditions they would test, or extract the conditions from a dated public experiment by the people who tested it. Record which method you used. Preserve source locations and important qualifications such as load direction, mounting, duration and units. Define each condition precisely enough to distinguish a related suggestion from an equivalent test.

Save the list separately from the ordinary user files. Each row needs a unique ID and a description. Additional source fields are preserved in the scored rows.

```json
{
  "prototype": "Name of the device",
  "checklist_source": "Author, dated test report and link",
  "conditions": [
    {"id": "A", "description": "Describe one condition here", "source": "Page or figure"}
  ]
}
```

```sh
python scripts/evaluate_prototype_pilot.py freeze checklist.json lock.json
```

Keep both files outside the project uploads and scenario prompt. Save the lock before opening the project. Its hash covers the exact checklist bytes. During scoring the evaluator checks the local freeze time against the server's batch start time. Both clocks must agree. Record who selected the conditions and whether they also operated the workbench.

## Use the workbench

Capture the exact starting files, project goal, requirements, baseline and discovery prompt. Work from a fresh project and record each manual intervention when it happens. Keep failed imports, unanswered questions, parameter translations and solver or UI changes in this record. If you run several discovery batches, identify the first one before reviewing the findings. Keep later attempts separate.

In **Discover scenarios**, select the saved generation. Once its runs finish, use **Download proposals (JSON)** and **Download results (JSON)** to save `batch.json` and `results.json` for the same batch. Keep both files for a failed generation as a record of the availability failure.

## Review the suggestions

For each checklist ID, cite a verbatim excerpt from a persisted title, hypothesis, question or missing capability. Explain where the generated condition agrees with the independent reference, and identify differences. Mark the origin as `supplied` if the operator had already given the relevant condition in the files, brief, baseline or prompt. Use `unprompted` only after checking those inputs. Use `unknown` when the intake record is incomplete.

```json
{
  "reviewer": "Who reviewed the match",
  "interventions": ["Converted dimensions from the source drawing to metres"],
  "conditions": [
    {
      "id": "A",
      "candidate_id": "copy the saved ID",
      "match": "equivalent",
      "quote": "exact words from the candidate",
      "reason": "Explain why the operating condition, range and units agree",
      "origin": "supplied",
      "controls": {
        "reference": {"example_input": 1},
        "variant": {"example_input": 2}
      }
    }
  ]
}
```

- Use `related` for a suggestion on the same topic with a material difference in load, location, timing or mechanism. Omit `controls` in that case.
- For a miss, record the ID, reason and `"candidate_id": null`. A verbatim batch-level question in `clarification` records a question separately.
- Supply `controls` when claiming a simulated match. Include each changed field from the saved plan, its value on each side, and any unchanged field needed to establish the condition. A field present on only one side of the plan should appear on that side of the claim. A completed, assessed comparison also needs matching reference, variant and suite IDs.

```sh
python scripts/evaluate_prototype_pilot.py score checklist.json lock.json batch.json results.json review.json --output report.json
```

The output counts simulated matches, equivalent proposals lacking verified execution, related suggestions, clarification-only coverage and misses. Its inventory shows which solver operation and project facts each candidate cited. The reviewer supplies the semantic judgment about each match. A passing or failing run refers to the recorded simulator criterion. Compare with the physical experiment separately, carrying through uncertainties and any unmodeled differences.

The local provider offers registered operations to the model and can request a corrected response or additional suggestions from that catalog. The workbench saves the model identity, prompt version and the resulting candidate. Per-candidate generation pass is unavailable in the current API. An intake-origin label describes what the operator supplied. Catalog prompting can still account for a condition absent from the intake.
