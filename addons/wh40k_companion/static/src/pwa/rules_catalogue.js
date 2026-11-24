/** @odoo-module **/

const PROSE_KEYS = new Set(["body", "ruleBody", "when", "target", "effect"]);

/** Drop army-rule body, detachment rule body, and stratagem when/target/effect. */
export function stripRuleProse(value) {
  if (Array.isArray(value)) {
    return value.map((item) => stripRuleProse(item));
  }
  if (!value || typeof value !== "object") {
    return value;
  }
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    if (PROSE_KEYS.has(key)) {
      continue;
    }
    out[key] = stripRuleProse(item);
  }
  return out;
}


  const BATTLE_SIZES = ["combat patrol", "incursion", "strike force", "onslaught", "strikeforce"];
  const MISSIONS = [
    "disruption",
    "priority assets",
    "purge the foe",
    "reconnaissance",
    "recon",
    "take and hold",
  ];
  const BREADCRUMBS = ["chaos", "imperium", "space marines", "xenos", "adeptus astartes"];

  function norm(value) {
    return String(value || "")
      .toLowerCase()
      .replace(/[’‘]/g, "'")
      .replace(/[^a-z0-9+]+/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function parsePts(raw) {
    const digits = String(raw || "").replace(/[^\d]/g, "");
    return digits ? Number(digits) : null;
  }

  function isBattleSize(name) {
    const n = norm(name);
    return BATTLE_SIZES.some((label) => n === label || n.startsWith(label + " "));
  }

  function isMission(name) {
    return MISSIONS.includes(norm(name));
  }

  function stripFooter(text) {
    return String(text || "")
      .replace(/\r\n/g, "\n")
      .split("\n")
      .filter((line) => {
        const t = line.trim();
        if (!t) return true;
        return !/exported with app version|created with newrecruit|^\s*data version\b/i.test(t);
      })
      .join("\n");
  }

  function splitDetachmentLine(line) {
    let value = String(line || "").trim();
    value = value.replace(/\s*[:：]\s*/, ": ");
    const keyed = value.match(/^(?:detachment)\b(?:\s*\[[^\]]*\])?\s*:\s*(.+)$/i);
    if (keyed) value = keyed[1].trim();
    value = value.replace(/\s*\(\s*\d*\s*(?:detachment points?|dp)\s*\)\s*$/i, "").trim();
    value = value.replace(/\s*\[\s*\d+\s*(?:detachment points?|dp)\s*\]\s*$/i, "").trim();
    const parts = value
      .split(/\s*,\s*and\s+|\s*,\s+|\s+and\s+/i)
      .map((part) =>
        part
          .replace(/\s*[\[\(]\s*\d+\s*(?:detachment points?|dp)\s*[\]\)]\s*$/i, "")
          .trim()
      )
      .filter(Boolean);
    return parts;
  }

  function configKey(line) {
    const match = line.match(
      /^(battle size|detachment|force disposition|faction|list name)\b(?:\s*\[[^\]]*\])?\s*:\s*(.+)$/i
    );
    if (!match) return null;
    return { key: match[1].toLowerCase(), value: match[2].trim() };
  }

  function sectionName(line) {
    const md = line.match(/^#{1,6}\s+(.+?)\s*$/);
    if (md) return md[1].replace(/\s*\(.*\)\s*$/, "").trim();
    if (/^[A-Z][A-Z0-9 /&-]{2,}$/.test(line)) return line.trim();
    const colon = line.match(/^([A-Za-z][\w /&'-]*):\s*$/);
    if (colon && !configKey(line)) return colon[1].trim();
    return null;
  }

  function unitHeader(line) {
    const match = line.match(/^(.+?)\s*(?:\(|\[)\s*([\d][\d,.'’\s]*)\s*(?:pts?|points?)\s*(?:\)|\])\s*$/i);
    if (!match) return null;
    return { name: match[1].trim(), points: parsePts(match[2]) };
  }

  function bulletOf(line) {
    const match = line.match(/^([ \t]*)([•◦*])\s+(.+?)\s*$/);
    if (!match) return null;
    const indent = match[1].replace(/\t/g, "  ").length;
    return { indent, text: match[3].trim(), bullet: true };
  }

  function continuationOf(line) {
    const match = line.match(/^([ \t]+)(\d+\s*[x×]\s+\S.*)$/);
    if (!match) return null;
    return { indent: match[1].replace(/\t/g, "  ").length, text: match[2].trim(), bullet: false };
  }

  function isAttachmentHeading(line) {
    return /^attached units$/i.test(line) || /^attached unit\s+\d+$/i.test(line);
  }

  function classifyItem(text) {
    const raw = text.replace(/^\d+\s*[x×]\s+/i, "").trim();
    if (/^warlord$/i.test(raw)) return { kind: "annotation", label: "Warlord" };
    if (/^leader$/i.test(raw)) return { kind: "annotation", label: "Leader" };
    const attached = raw.match(/^attached\s+(?:as|to)\s*:\s*(.+)$/i);
    if (attached) return { kind: "annotation", label: `Attached ${/^\s*attached\s+to/i.test(raw) ? "to" : "as"}: ${attached[1].trim()}` };
    const leading = raw.match(/^(?:leading|leader)\s*:\s*(.+)$/i);
    if (leading) return { kind: "annotation", label: `Leading: ${leading[1].trim()}` };
    const enh = raw.match(/^(?:e|enhancements?)\s*:\s*(.+)$/i);
    if (enh) {
      const name = enh[1].replace(/\s*\(\+\s*[\d,]+\s*(?:pts?|points?)\s*\)\s*$/i, "").trim();
      return { kind: "enhancement", name };
    }
    const plain = raw.replace(/\s*\(\+\s*[\d,]+\s*(?:pts?|points?)\s*\)\s*$/i, "").trim();
    return { kind: "gear", name: plain };
  }

  function consumeUnits(lines, start) {
    const units = [];
    let current = null;
    let section = null;
    function flush() {
      if (!current) return;
      current.items = shapeItems(current.bullets);
      delete current.bullets;
      units.push(current);
      current = null;
    }
    for (let i = start; i < lines.length; i++) {
      const line = lines[i].trimEnd();
      const trimmed = line.trim();
      if (!trimmed) continue;
      const bullet = bulletOf(line);
      if (bullet) {
        if (current) current.bullets.push(bullet);
        continue;
      }
      const cont = continuationOf(line);
      if (cont && current) {
        current.bullets.push(cont);
        continue;
      }
      if (isAttachmentHeading(trimmed)) {
        flush();
        section = trimmed;
        continue;
      }
      const header = unitHeader(trimmed);
      if (header && !isBattleSize(header.name)) {
        flush();
        current = { name: header.name, points: header.points, section, bullets: [] };
        continue;
      }
      const nextSection = sectionName(trimmed);
      if (nextSection) {
        flush();
        section = nextSection;
        continue;
      }
      if (current && !configKey(trimmed)) {
        current.bullets.push({ indent: 99, text: trimmed, bullet: false });
      }
    }
    flush();
    return units;
  }

  function shapeItems(bullets) {
    return bullets.map((bullet, index) => {
      const next = bullets[index + 1];
      const isModel = Boolean(next && next.bullet && next.indent > bullet.indent);
      const item = classifyItem(bullet.text);
      item.raw = bullet.text;
      item.isModel = isModel && item.kind === "gear";
      return item;
    });
  }

  function parseLabeled(text) {
    const lines = text.split("\n");
    const parsed = blankParsed();
    let start = lines.length;
    for (let i = 0; i < lines.length; i++) {
      const trimmed = lines[i].trim();
      if (!trimmed || /^\+{3,}$/.test(trimmed) || /^#\s+\+\+/.test(trimmed)) continue;
      const key = configKey(trimmed);
      if (key) {
        if (key.key === "faction") parsed.faction = key.value;
        if (key.key === "battle size") parsed.battleSize = key.value;
        if (key.key === "force disposition") parsed.mission = key.value;
        if (key.key === "detachment") parsed.detachmentNames = splitDetachmentLine(key.value);
        if (key.key === "list name" && !parsed.name) parsed.name = key.value;
        continue;
      }
      const header = unitHeader(trimmed);
      if (header && isBattleSize(header.name)) {
        parsed.battleSize = trimmed;
        parsed.limit = header.points;
        continue;
      }
      const sec = sectionName(trimmed);
      if (sec && norm(sec) === "configuration") continue;
      if (header && !parsed.name) {
        parsed.name = header.name;
        parsed.points = header.points;
        continue;
      }
      if (header || sec || bulletOf(lines[i])) {
        start = i;
        break;
      }
      if (!parsed.name) parsed.name = trimmed.replace(/^#+\s*/, "");
    }
    parsed.units = consumeUnits(lines, start);
    if (parsed.battleSize && parsed.limit == null) {
      const size = unitHeader(parsed.battleSize);
      parsed.limit = size ? size.points : parsePts(parsed.battleSize);
    }
    return parsed;
  }

  function parseHeaderless(text) {
    const lines = text.split("\n");
    const parsed = blankParsed();
    const preamble = [];
    let consumedTitle = false;
    let preambleOpen = true;
    let section = null;
    let current = null;
    const units = [];
    function flush() {
      if (!current) return;
      current.items = shapeItems(current.bullets);
      delete current.bullets;
      units.push(current);
      current = null;
    }
    for (const raw of lines) {
      const line = raw.trim();
      if (!line) continue;
      const bullet = bulletOf(raw);
      if (bullet) {
        preambleOpen = false;
        if (current) current.bullets.push(bullet);
        continue;
      }
      const cont = continuationOf(raw);
      if (cont && current) {
        current.bullets.push(cont);
        continue;
      }
      const header = unitHeader(line);
      if (header) {
        if (isBattleSize(header.name)) {
          parsed.battleSize = line;
          parsed.limit = header.points;
          continue;
        }
        if (!consumedTitle && !current && units.length === 0) {
          consumedTitle = true;
          parsed.name = header.name;
          parsed.points = header.points;
          continue;
        }
        preambleOpen = false;
        flush();
        current = { name: header.name, points: header.points, section, bullets: [] };
        continue;
      }
      const nextSection = isAttachmentHeading(line) ? line : sectionName(line);
      if (nextSection) {
        preambleOpen = false;
        flush();
        section = nextSection;
        continue;
      }
      if (!consumedTitle && !current && units.length === 0) {
        consumedTitle = true;
        parsed.name = line;
      } else if (preambleOpen && !current && units.length === 0) {
        preamble.push(line);
      } else if (current) {
        current.bullets.push({ indent: 99, text: line, bullet: false });
      }
    }
    flush();
    const parts = preamble.slice();
    const missionAt = parts.findIndex((part) => isMission(part));
    if (missionAt >= 0) parsed.mission = parts.splice(missionAt, 1)[0];
    if (parts.length) {
      let faction = parts.shift();
      if (BREADCRUMBS.includes(norm(faction)) && parts.length) faction = parts.shift();
      parsed.faction = faction;
      parsed.detachmentNames = parts.flatMap((part) => splitDetachmentLine(part));
    }
    parsed.units = units;
    return parsed;
  }

  function blankParsed() {
    return {
      name: "",
      points: null,
      limit: null,
      faction: "",
      battleSize: "",
      mission: "",
      detachmentNames: [],
      units: [],
    };
  }

  function hasLabeledConfig(text) {
    return text.split("\n").some((line) => configKey(line.trim()));
  }

  function parseRoster(text) {
    const clean = stripFooter(text);
    return hasLabeledConfig(clean) ? parseLabeled(clean) : parseHeaderless(clean);
  }

  function weaponKey(name) {
    let s = String(name || "")
      .replace(/[➤•◦*]/g, " ")
      .replace(/[–—−]/g, "-")
      .replace(/[’‘]/g, "'")
      .toLowerCase();
    const hunter = /\bhunter\b/.test(s);
    s = s.replace(/\(.*?\)/g, " ");
    s = s.replace(/\bhunter\b/g, " ");
    s = s.replace(/\b(vs|monster|vehicle)\b/g, " ");
    s = s.replace(/[^a-z0-9+-]+/g, " ").replace(/\s+/g, " ").trim();
    const bits = s.split("-").map((bit) => bit.trim()).filter(Boolean);
    return { base: bits[0] || "", mode: bits.slice(1).join(" "), hunter };
  }

  function sameWeapon(a, b) {
    return a.base === b.base && a.mode === b.mode && a.hunter === b.hunter && a.base.length > 0;
  }

  function matchByName(list, raw, nameOf) {
    const wanted = norm(raw);
    return list.find((item) => norm(nameOf(item)) === wanted) || null;
  }

  function matchFaction(raw, index) {
    if (!raw) return null;
    const wanted = norm(raw);
    const factions = index.factions || [];
    const exact = factions.find((faction) => norm(faction.name) === wanted || norm(faction.id) === wanted);
    if (exact) return exact;
    const tail = factions
      .filter((faction) => wanted.endsWith(norm(faction.name)) && norm(faction.name).length > 3)
      .sort((a, b) => norm(b.name).length - norm(a.name).length);
    return tail[0] || null;
  }

  function matchDetachment(raw, index) {
    for (const faction of index.factions || []) {
      const found = matchByName(faction.detachments || [], raw, (det) => det.name);
      if (found) return { ...found, factionId: faction.id, factionName: faction.name };
    }
    return null;
  }

  function factionById(index, id) {
    return (index.factions || []).find((faction) => faction.id === id) || null;
  }

  function addUnits(pool, seen, units) {
    for (const unit of units || []) {
      const key = (unit.source || "") + ":" + (unit.id || unit.name);
      if (seen.has(key)) continue;
      seen.add(key);
      pool.push(unit);
    }
  }

  function sharedUnits(index, faction) {
    if (!faction || !(faction.sharedUnitIds || []).length) return [];
    const marines = factionById(index, "space-marines");
    const byId = new Map(((marines && marines.units) || []).map((unit) => [unit.id, unit]));
    const rows = [];
    for (const id of faction.sharedUnitIds || []) {
      const unit = byId.get(id);
      if (unit) rows.push(unit);
    }
    return rows;
  }

  // Own datasheets, then that book's shared Space Marine units. Later factions
  // are only the books that own a detachment named on the list, so a duplicate
  // datasheet name stays on the roster's faction.
  function addFactionUnits(pool, seen, index, faction) {
    if (!faction) return;
    addUnits(pool, seen, faction.units);
    addUnits(pool, seen, sharedUnits(index, faction));
  }

  function unitPool(index, faction, detachments) {
    const pool = [];
    const seen = new Set();
    addFactionUnits(pool, seen, index, faction);
    for (const det of detachments || []) {
      if (!det.factionId || (faction && det.factionId === faction.id)) continue;
      addFactionUnits(pool, seen, index, factionById(index, det.factionId));
    }
    return pool;
  }

  function matchUnit(name, pool, index) {
    const direct = matchByName(pool, name, (row) => row.name);
    if (direct) return direct;
    const wanted = norm(name);
    const hits = [];
    for (const faction of index.factions || []) {
      for (const unit of faction.units || []) {
        if (norm(unit.name) === wanted) hits.push(unit);
      }
    }
    return hits.length === 1 ? hits[0] : null;
  }

  function matchGear(name, unit, enhancements) {
    const key = weaponKey(name);
    if (unit) {
      const hits = (unit.weapons || []).filter((weapon) => sameWeapon(weaponKey(weapon.name), key));
      if (hits.length === 1) return { status: "weapon", weapon: hits[0] };
      if (hits.length > 1) return { status: "modes", weapons: hits };
      const ability = (unit.abilityNames || []).find((abilityName) => norm(abilityName) === norm(name));
      if (ability) return { status: "ability", name: ability };
    }
    const enh = (enhancements || []).find((row) => norm(row.name) === norm(name));
    if (enh) return { status: "enhancement", enhancement: { name: enh.name, points: enh.points, detachmentId: enh.detachmentId } };
    if (unit && key.mode === "" && !key.hunter && key.base) {
      const family = (unit.weapons || []).filter((weapon) => weaponKey(weapon.name).base === key.base && !weaponKey(weapon.name).hunter);
      if (family.length > 1) return { status: "modes", weapons: family };
      if (family.length === 1) return { status: "weapon", weapon: family[0] };
    }
    return { status: "unmatched" };
  }

  function matchRoster(parsed, index) {
    const faction = matchFaction(parsed.faction, index);
    const detachments = (parsed.detachmentNames || []).map((name) => {
      const match = matchDetachment(name, index);
      return {
        raw: name,
        id: match ? match.id : null,
        name: match ? match.name : null,
        ruleName: match ? match.ruleName : null,
        ruleBody: match ? match.ruleBody || "" : "",
        ruleFlavor: match ? match.ruleFlavor || "" : "",
        stratagems: match ? match.stratagems || [] : [],
        factionId: match ? match.factionId : null,
      };
    });
    const pool = unitPool(index, faction, detachments);
    const enhancements = [];
    const matchedDets = detachments.filter((det) => det.id);
    for (const factionRow of index.factions || []) {
      for (const enh of factionRow.enhancements || []) {
        if (matchedDets.some((det) => det.id === enh.detachmentId)) enhancements.push(enh);
      }
    }
    const units = (parsed.units || []).map((unit) => {
      const datasheet = matchUnit(unit.name, pool, index);
      const items = (unit.items || []).map((item) => {
        if (item.kind === "annotation" || item.isModel) return { ...item, match: null };
        if (item.kind === "enhancement") {
          const found = enhancements.find((enh) => norm(enh.name) === norm(item.name));
          return {
            ...item,
            match: found
              ? { status: "enhancement", enhancement: { name: found.name, points: found.points, detachmentId: found.detachmentId } }
              : { status: "unmatched" },
          };
        }
        return { ...item, match: matchGear(item.name, datasheet, enhancements) };
      });
      return {
        name: unit.name,
        points: unit.points,
        section: unit.section || "",
        datasheetId: datasheet ? datasheet.id : null,
        datasheetName: datasheet ? datasheet.name : null,
        source: datasheet ? datasheet.source : null,
        profiles: datasheet ? datasheet.profiles || [] : [],
        items,
      };
    });
    return {
      meta: {
        name: parsed.name,
        points: parsed.points,
        limit: parsed.limit,
        factionRaw: parsed.faction,
        factionId: faction ? faction.id : null,
        factionName: faction ? faction.name : null,
        armyRule: faction
          ? {
              id: faction.armyRule.id,
              name: faction.armyRule.name,
              body: faction.armyRule.body || "",
              flavor: faction.armyRule.flavor || "",
            }
          : null,
        battleSize: parsed.battleSize,
        mission: parsed.mission,
      },
      detachments,
      units,
    };
  }

  

export {
  parseRoster,
  matchRoster,
  splitDetachmentLine,
  norm,
  weaponKey,
};
