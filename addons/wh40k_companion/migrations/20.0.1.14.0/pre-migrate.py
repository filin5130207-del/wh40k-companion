def migrate(cr, version):
    """Retire OWL client action xml id so it can be recreated as act_url."""
    cr.execute(
        """
        DELETE FROM ir_act_client
         WHERE id IN (
            SELECT res_id FROM ir_model_data
             WHERE module = 'wh40k_companion'
               AND name = 'action_wh40k_companion_client'
               AND model = 'ir.actions.client'
         )
        """
    )
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'wh40k_companion'
           AND name = 'action_wh40k_companion_client'
           AND model = 'ir.actions.client'
        """
    )
