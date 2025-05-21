odoo.define('theme_prime.service_worker_register', function (require) {
'use strict';

require('web.dom_ready');
var Widget = require('web.Widget');
const { getCookie, setCookie } = require('web.utils.cookies');

var html = document.documentElement;
var websiteID = html.getAttribute('data-website-id') || 0;

var PWAiOSPopupWidget = Widget.extend({
    template: 'theme_prime.pwa_ios_popup',
    events: {
        'click': '_onClickPopup',
    },
    init: function () {
        this._super.apply(this, arguments);
        this.websiteID = websiteID;
    },
    _onClickPopup: function () {
        setCookie(_.str.sprintf('tp-pwa-ios-popup-%s', websiteID), true);
        this.destroy();
    },
});

if (odoo.dr_theme_config.pwa_active) {
    activateServiceWorker();
} else {
    deactivateServiceWorker();
}

function displayPopupForiOS () {
    // Detects if device is on iOS
    const isIos = () => {
        return /^((?!chrome|android).)*safari/i.test(navigator.userAgent) && (navigator.userAgent.match(/iPad/i) || navigator.userAgent.match(/iPhone/i));
    }

    // Detects if device is in standalone mode
    const isInStandaloneMode = () => ('standalone' in window.navigator) && (window.navigator.standalone);

    // Checks if should display install popup notification
    if (isIos() && !isInStandaloneMode()) {
        if (!getCookie(_.str.sprintf('tp-pwa-ios-popup-%s', websiteID))) {
            var widget = new PWAiOSPopupWidget();
            widget.appendTo($('body'));
        }
    }
}

function activateServiceWorker() {
    if (navigator.serviceWorker) {
        navigator.serviceWorker.register('/service_worker.js').then(function (registration) {
            console.log('ServiceWorker registration successful with scope:',  registration.scope);
            displayPopupForiOS();
        }).catch(function(error) {
            console.log('ServiceWorker registration failed:', error);
        });
    }
}

function deactivateServiceWorker() {
    if (navigator.serviceWorker) {
        navigator.serviceWorker.getRegistrations().then(function (registrations) {
            _.each(registrations, function (r) {
                r.unregister();
                console.log('ServiceWorker removed successfully');
            });
        }).catch(function (err) {
            console.log('Service worker unregistration failed: ', err);
        });
    }
}

});
