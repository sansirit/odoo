odoo.define('social.stream_post_formatter_mixin', function (require) {
"use strict";

return {
    /**
     * Wraps (simple https) links around anchors
     * Regex from: https://stackoverflow.com/questions/19484370/how-do-i-automatically-wrap-text-urls-in-anchor-tags
     *
     * @param {String} formattedValue
     * @private
     */
    _formatStreamPost: function (formattedValue) {
        return formattedValue
            .replace(/(?:(https?\:\/\/[^\s|<]+))/g, "<a href='$1' target='_blank' rel='noreferrer noopener'>$1</a>");
    }
};

});
