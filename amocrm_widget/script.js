/**
 * SalesBot AI Widget for AmoCRM/Kommo
 * AI-powered call analysis and deal insights
 */
define(['jquery', 'underscore'], function($, _) {
    var CustomWidget = function() {
        var self = this;
        var w_code = self.get_settings().widget_code;

        /**
         * Get API URL from settings
         */
        this.getApiUrl = function() {
            return self.get_settings().api_url || 'https://saleswhisper.pro/api';
        };

        /**
         * Get API Key from settings
         */
        this.getApiKey = function() {
            return self.get_settings().api_key || '';
        };

        /**
         * Make API request to SalesBot backend
         */
        this.apiRequest = function(endpoint, method, data) {
            var deferred = $.Deferred();
            var url = this.getApiUrl() + endpoint;

            $.ajax({
                url: url,
                type: method || 'GET',
                data: data ? JSON.stringify(data) : null,
                contentType: 'application/json',
                headers: {
                    'X-API-Key': this.getApiKey()
                },
                success: function(response) {
                    deferred.resolve(response);
                },
                error: function(xhr, status, error) {
                    console.error('SalesBot API Error:', error);
                    deferred.reject(error);
                }
            });

            return deferred.promise();
        };

        /**
         * Render call analysis panel in lead card
         */
        this.renderLeadCard = function() {
            var lead_id = AMOCRM.data.current_card.id;
            var $widget_panel = $('[data-id="' + w_code + '"]');

            if (!$widget_panel.length) {
                return false;
            }

            // Show loading state
            $widget_panel.html(self.render({
                ref: '/templates/loading.twig'
            }, {}));

            // Fetch analysis data
            self.apiRequest('/widget/lead/' + lead_id + '/analysis', 'GET')
                .then(function(data) {
                    $widget_panel.html(self.render({
                        ref: '/templates/lead_card.twig'
                    }, {
                        lead_id: lead_id,
                        analysis: data.analysis || {},
                        calls: data.calls || [],
                        priority: data.priority || 'normal',
                        quality_score: data.quality_score || 0,
                        recommendations: data.recommendations || [],
                        commitments: data.commitments || [],
                        sentiment: data.sentiment || 'neutral',
                        last_updated: data.last_updated || ''
                    }));

                    // Bind actions after render
                    self.bindLeadCardActions($widget_panel);
                })
                .fail(function(error) {
                    $widget_panel.html(self.render({
                        ref: '/templates/error.twig'
                    }, {
                        error_message: self.i18n('error.load_failed')
                    }));
                });

            return true;
        };

        /**
         * Render contact card panel
         */
        this.renderContactCard = function() {
            var contact_id = AMOCRM.data.current_card.id;
            var $widget_panel = $('[data-id="' + w_code + '"]');

            if (!$widget_panel.length) {
                return false;
            }

            $widget_panel.html(self.render({
                ref: '/templates/loading.twig'
            }, {}));

            self.apiRequest('/widget/contact/' + contact_id + '/history', 'GET')
                .then(function(data) {
                    $widget_panel.html(self.render({
                        ref: '/templates/contact_card.twig'
                    }, {
                        contact_id: contact_id,
                        total_calls: data.total_calls || 0,
                        avg_quality: data.avg_quality || 0,
                        sentiment_history: data.sentiment_history || [],
                        key_topics: data.key_topics || []
                    }));
                })
                .fail(function(error) {
                    $widget_panel.html(self.render({
                        ref: '/templates/error.twig'
                    }, {
                        error_message: self.i18n('error.load_failed')
                    }));
                });

            return true;
        };

        /**
         * Bind actions in lead card panel
         */
        this.bindLeadCardActions = function($panel) {
            // Refresh analysis button
            $panel.on('click', '.js-salesbot-refresh', function(e) {
                e.preventDefault();
                var lead_id = $(this).data('lead-id');

                $(this).addClass('loading');

                self.apiRequest('/widget/lead/' + lead_id + '/analyze', 'POST')
                    .then(function(data) {
                        self.renderLeadCard();
                        self.showNotification('success', self.i18n('notification.analysis_started'));
                    })
                    .fail(function() {
                        self.showNotification('error', self.i18n('error.analysis_failed'));
                    })
                    .always(function() {
                        $panel.find('.js-salesbot-refresh').removeClass('loading');
                    });
            });

            // Create task from recommendation
            $panel.on('click', '.js-salesbot-create-task', function(e) {
                e.preventDefault();
                var $btn = $(this);
                var lead_id = $btn.data('lead-id');
                var task_text = $btn.data('task-text');
                var deadline_days = $btn.data('deadline-days') || 1;

                $btn.addClass('loading');

                self.apiRequest('/widget/lead/' + lead_id + '/create-task', 'POST', {
                    text: task_text,
                    deadline_days: deadline_days
                })
                    .then(function(data) {
                        self.showNotification('success', self.i18n('notification.task_created'));
                        $btn.addClass('created').text(self.i18n('button.task_created'));
                    })
                    .fail(function() {
                        self.showNotification('error', self.i18n('error.task_failed'));
                    })
                    .always(function() {
                        $btn.removeClass('loading');
                    });
            });

            // View call details
            $panel.on('click', '.js-salesbot-view-call', function(e) {
                e.preventDefault();
                var call_id = $(this).data('call-id');
                self.showCallDetailsModal(call_id);
            });

            // Toggle section
            $panel.on('click', '.js-salesbot-toggle', function(e) {
                e.preventDefault();
                $(this).closest('.salesbot-section').toggleClass('collapsed');
            });
        };

        /**
         * Show call details modal
         */
        this.showCallDetailsModal = function(call_id) {
            self.apiRequest('/widget/call/' + call_id + '/details', 'GET')
                .then(function(data) {
                    var modal = new (require('lib/components/base/modal'))({
                        class_name: 'salesbot-call-modal',
                        init: function($modal_body) {
                            $modal_body.html(self.render({
                                ref: '/templates/call_modal.twig'
                            }, {
                                call: data.call || {},
                                transcription: data.transcription || '',
                                analysis: data.analysis || {},
                                scores: data.scores || {},
                                recommendations: data.recommendations || [],
                                objections: data.objections || [],
                                sentiment_timeline: data.sentiment_timeline || []
                            }));

                            return true;
                        },
                        destroy: function() {}
                    });
                })
                .fail(function() {
                    self.showNotification('error', self.i18n('error.load_failed'));
                });
        };

        /**
         * Show notification
         */
        this.showNotification = function(type, message) {
            if (type === 'error') {
                APP.notifications.add_error({
                    header: 'SalesBot',
                    text: message
                });
            } else {
                APP.notifications.show_message({
                    header: 'SalesBot',
                    text: message
                });
            }
        };

        /**
         * Render settings page
         */
        this.renderSettings = function($settings_body) {
            $settings_body.html(self.render({
                ref: '/templates/settings.twig'
            }, {
                api_url: self.get_settings().api_url || '',
                api_key: self.get_settings().api_key || '',
                status: self.get_status()
            }));

            // Test connection button
            $settings_body.on('click', '.js-salesbot-test-connection', function(e) {
                e.preventDefault();
                var $btn = $(this);
                var $status = $settings_body.find('.js-connection-status');

                $btn.addClass('loading');
                $status.text(self.i18n('settings.testing'));

                var api_url = $settings_body.find('[name="api_url"]').val();
                var api_key = $settings_body.find('[name="api_key"]').val();

                $.ajax({
                    url: api_url + '/widget/health',
                    type: 'GET',
                    headers: {
                        'X-API-Key': api_key
                    },
                    success: function(response) {
                        $status.text(self.i18n('settings.connection_ok')).addClass('success');
                    },
                    error: function() {
                        $status.text(self.i18n('settings.connection_failed')).addClass('error');
                    },
                    complete: function() {
                        $btn.removeClass('loading');
                    }
                });
            });

            return true;
        };

        /**
         * Widget callbacks
         */
        this.callbacks = {
            /**
             * Render callback - called when widget area is visible
             */
            render: function() {
                var current_area = self.system().area;

                // Lead card
                if (current_area === 'lcard') {
                    return self.renderLeadCard();
                }

                // Contact card
                if (current_area === 'ccard') {
                    return self.renderContactCard();
                }

                return true;
            },

            /**
             * Init callback - called once on load
             */
            init: function() {
                // Load custom CSS
                if (!$('#salesbot-widget-styles').length) {
                    $('head').append(
                        '<link id="salesbot-widget-styles" rel="stylesheet" href="/widgets/' + w_code + '/style.css">'
                    );
                }

                console.log('SalesBot Widget initialized');
                return true;
            },

            /**
             * Bind actions - called after render
             */
            bind_actions: function() {
                return true;
            },

            /**
             * Settings callback - render settings page
             */
            settings: function($settings_body) {
                return self.renderSettings($settings_body);
            },

            /**
             * OnSave callback - validate and save settings
             */
            onSave: function() {
                var api_url = $('[name="api_url"]').val();
                var api_key = $('[name="api_key"]').val();

                if (!api_url || !api_key) {
                    self.showNotification('error', self.i18n('error.settings_required'));
                    return false;
                }

                // Validate URL format
                if (!api_url.match(/^https?:\/\//)) {
                    self.showNotification('error', self.i18n('error.invalid_url'));
                    return false;
                }

                return true;
            },

            /**
             * Destroy callback - cleanup
             */
            destroy: function() {
                // Cleanup any event handlers
            },

            /**
             * Digital Pipeline callback
             */
            dpSettings: function() {
                return true;
            }
        };

        return this;
    };

    return CustomWidget;
});
