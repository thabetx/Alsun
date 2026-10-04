from paragraph_format import concatenate_paragraph_segements, build_paragraph_display_parts

# A row is one line of the table:
#   {"id": "...", "segments": [...], "source_blocks": [{"id": ..., "page": ..., "polygon": ...}]}
# A merged row also has "merged_from" (the rows it was made of) and every segment of it has
# "merge_trail" (where the segment came from) so the merge can be undone, even after edits.


def explain_merge_problem(all_rows, selected_row_ids):
    # None = the merge is possible; otherwise the reason (the front shows it on the disabled button)
    if len(selected_row_ids) < 2:
        return "select at least two rows to merge"

    row_ids = [row["id"] for row in all_rows]
    if len(set(selected_row_ids)) != len(selected_row_ids):
        return "a row is selected twice"
    for selected_id in selected_row_ids:
        if selected_id not in row_ids:
            return f"row {selected_id} does not exist"

    positions = sorted(row_ids.index(selected_id) for selected_id in selected_row_ids)
    if positions != list(range(positions[0], positions[0] + len(positions))):
        return "only rows that are next to each other can be merged"

    return None


def describe_row_before_merge(row):
    # what we need to bring the row back; a row that is already merged keeps its own merged_from
    description = {"id": row["id"], "source_blocks": row["source_blocks"]}
    if "merged_from" in row:
        description["merged_from"] = row["merged_from"]
    return description


def merge_rows(all_rows, selected_row_ids):
    problem = explain_merge_problem(all_rows, selected_row_ids)
    if problem:
        raise ValueError(problem)

    # merge in the order of the table, not in the order of the clicks
    rows_to_merge = [row for row in all_rows if row["id"] in selected_row_ids]

    merged_segments = []
    for row in rows_to_merge:
        for segment in row["segments"]:
            trail = segment.get("merge_trail", []) + [{"row_id": row["id"], "segment_id": segment["id"]}]
            merged_segments.append({**segment, "id": f"seg_{len(merged_segments) + 1}", "merge_trail": trail})

    merged_row = {
        "id": "+".join(row["id"] for row in rows_to_merge),
        "segments": merged_segments,
        "source_blocks": [block for row in rows_to_merge for block in row["source_blocks"]],
        "merged_from": [describe_row_before_merge(row) for row in rows_to_merge],
    }

    first_position = all_rows.index(rows_to_merge[0])
    rows_before = all_rows[:first_position]
    rows_after = all_rows[first_position + len(rows_to_merge):]
    return rows_before + [merged_row] + rows_after


def unmerge_row(all_rows, merged_row_id):
    merged_row = next((row for row in all_rows if row["id"] == merged_row_id), None)
    if merged_row is None or "merged_from" not in merged_row:
        raise ValueError("this row is not a merged row")

    # every segment goes back to its own row, with the text it has now (edits are kept)
    restored_segments = {source["id"]: [] for source in merged_row["merged_from"]}
    for segment in merged_row["segments"]:
        trail = segment.get("merge_trail")
        if not trail or trail[-1]["row_id"] not in restored_segments:
            raise ValueError("this row can't be unmerged anymore, its segments changed")
        restored = {**segment, "id": trail[-1]["segment_id"]}
        if trail[:-1]:
            restored["merge_trail"] = trail[:-1]
        else:
            del restored["merge_trail"]
        restored_segments[trail[-1]["row_id"]].append(restored)

    restored_rows = []
    for source in merged_row["merged_from"]:
        restored_row = {"id": source["id"], "segments": restored_segments[source["id"]], "source_blocks": source["source_blocks"]}
        if "merged_from" in source:
            restored_row["merged_from"] = source["merged_from"]
        restored_rows.append(restored_row)

    position = all_rows.index(merged_row)
    return all_rows[:position] + restored_rows + all_rows[position + 1:]


def build_rows_response(all_rows):
    return {
        "rows": [
            {
                "id": row["id"],
                "paragraph": concatenate_paragraph_segements(row["segments"]),
                "parts": build_paragraph_display_parts(row["segments"]),
                "segments": row["segments"],
                "source_blocks": row["source_blocks"],
                "is_merged": "merged_from" in row,
            }
            for row in all_rows
        ]
    }
