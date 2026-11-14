/** @odoo-module **/

import { proxy } from "@odoo/owl";
import {
    API,
    extractJoinToken,
    rememberJoinToken,
    clearRememberedJoinToken,
    parseOdooDatetime,
    createInitialState,
    filterEligibleRosters,
    snapshotUnit,
    pushUndoEntry,
    popUndoEntry,
    applyUnitFieldDelta,
    destroyUnitInPlace,
    UNDO_STACK_LIMIT,
} from "./battle_helpers";

export {
    API,
    extractJoinToken,
    rememberJoinToken,
    clearRememberedJoinToken,
    parseOdooDatetime,
    createInitialState,
    filterEligibleRosters,
    snapshotUnit,
    pushUndoEntry,
    popUndoEntry,
    applyUnitFieldDelta,
    destroyUnitInPlace,
    UNDO_STACK_LIMIT,
};

/**
 * Owl proxy battle store. Mutations should go through named actions on the
 * CompanionApp controller so OWL re-renders stay predictable.
 */
export function createBattleStore(initialJoinToken = "") {
    return proxy(createInitialState(initialJoinToken));
}
