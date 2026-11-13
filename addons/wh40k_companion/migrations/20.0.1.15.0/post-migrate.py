import json
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Backfill wh40k.match.unit.line from legacy unit_state JSON when empty."""
    cr.execute(
        """
        SELECT m.id, m.unit_state
          FROM wh40k_match m
         WHERE m.unit_state IS NOT NULL
           AND m.unit_state NOT IN ('', '{}')
           AND NOT EXISTS (
                SELECT 1 FROM wh40k_match_unit_line l WHERE l.match_id = m.id
           )
        """
    )
    rows = cr.fetchall()
    created = 0
    for match_id, unit_state in rows:
        try:
            data = json.loads(unit_state or "{}")
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict):
            continue
        undo = data.get("undo") if isinstance(data.get("undo"), dict) else {}
        for side in ("host", "guest"):
            entries = data.get(side) or []
            if not isinstance(entries, list):
                continue
            for entry in entries:
                if not isinstance(entry, dict) or not entry.get("unit_id"):
                    continue
                unit_id = int(entry["unit_id"])
                # Skip orphan unit refs
                cr.execute("SELECT 1 FROM wh40k_unit WHERE id = %s", (unit_id,))
                if not cr.fetchone():
                    continue
                stack = undo.get(str(unit_id), undo.get(unit_id, []))
                if not isinstance(stack, list):
                    stack = []
                cr.execute(
                    """
                    INSERT INTO wh40k_match_unit_line
                        (match_id, unit_id, side, name, models, models_remaining,
                         wounds, wounds_remaining, destroyed, undo_stack)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        match_id,
                        unit_id,
                        side,
                        entry.get("name") or "Unit",
                        int(entry.get("models") or 1),
                        int(entry.get("models_remaining") or 0),
                        int(entry.get("wounds") or 1),
                        int(entry.get("wounds_remaining") or 0),
                        bool(entry.get("destroyed")),
                        json.dumps(stack[-20:]),
                    ),
                )
                created += 1
    # Best-effort owner backfill for rules linked to rosters.
    cr.execute(
        """
        UPDATE wh40k_rule r
           SET owner_partner_id = sub.partner_id
          FROM (
                SELECT rel.rule_id, roster.partner_id
                  FROM wh40k_force_army_rule_rel rel
                  JOIN wh40k_force force ON force.id = rel.force_id
                  JOIN wh40k_roster roster ON roster.id = force.roster_id
               ) sub
         WHERE r.id = sub.rule_id
           AND r.owner_partner_id IS NULL
        """
    )
    cr.execute(
        """
        UPDATE wh40k_rule r
           SET owner_partner_id = sub.partner_id
          FROM (
                SELECT rel.rule_id, roster.partner_id
                  FROM wh40k_detachment_rule_rel rel
                  JOIN wh40k_detachment det ON det.id = rel.detachment_id
                  JOIN wh40k_force force ON force.id = det.force_id
                  JOIN wh40k_roster roster ON roster.id = force.roster_id
               ) sub
         WHERE r.id = sub.rule_id
           AND r.owner_partner_id IS NULL
        """
    )
    _logger.info("WH40k 20.0.1.15.0: migrated %s match unit lines", created)
