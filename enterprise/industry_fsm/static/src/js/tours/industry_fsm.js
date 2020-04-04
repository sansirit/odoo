odoo.define('industry_fsm.tour', function (require) {
"use strict";

var core = require('web.core');
var tour = require('web_tour.tour');

var _t = core._t;

tour.register('industry_fsm_tour', {
    url: "/web",
}, [{
    trigger: '.o_app[data-menu-xmlid="industry_fsm.menu_fsm_root"]',
    content: _t('Start to manage your Onsite Intervention with the Field Service app.'),
    position: 'bottom',
}, {
    trigger: '.o-kanban-button-new',
    extra_trigger: '.o_fsm_kanban',
    content: _t('Create and plan your first Field Service Task'),
    position: 'bottom',

}]);

});
