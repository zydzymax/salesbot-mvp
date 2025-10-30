define(['jquery'], function($) {
    var CustomWidget = function() {
        var self = this;

        this.callbacks = {
            settings: function() {
                return true;
            },

            init: function() {
                return true;
            },

            bind_actions: function() {
                return true;
            },

            render: function() {
                var server_url = self.get_settings().server_url || 'http://localhost:8000';
                var current_area = this.system().area;
                var current_page = this.system().page;

                console.log('SalesBot Widget: Rendering in area:', current_area);

                // Показываем в настройках
                if (current_area === 'settings' || current_area === 'advanced_settings') {
                    this.render_dashboard_in_settings(server_url);
                }

                // Показываем в карточке лида с информацией о менеджере
                if (current_area === 'lcard') {
                    this.render_manager_info(server_url);
                }

                return true;
            },

            render_dashboard_in_settings: function(server_url) {
                var $container = $('.widget_settings_block__descr');

                if ($container.length === 0) {
                    $container = $('body');
                }

                var dashboard_html =
                    '<div class="salesbot-dashboard-container" style="margin-top: 20px;">' +
                        '<div style="background: white; padding: 15px; border-radius: 8px; margin-bottom: 10px;">' +
                            '<h2 style="margin: 0; color: #333; font-size: 20px;">📊 Дашборд Команды Продаж</h2>' +
                            '<p style="margin: 5px 0 0 0; color: #666; font-size: 14px;">Метрики качества, рейтинги и алерты</p>' +
                        '</div>' +
                        '<div style="position: relative; width: 100%; height: 800px; background: white; border-radius: 8px; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1);">' +
                            '<iframe src="' + server_url + '/admin/" ' +
                                'style="width: 100%; height: 100%; border: none;" ' +
                                'frameborder="0" ' +
                                'allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture">' +
                            '</iframe>' +
                        '</div>' +
                    '</div>';

                $container.append(dashboard_html);
            },

            render_manager_info: function(server_url) {
                // Получаем ID ответственного менеджера из AmoCRM
                var lead = this.system().lead;
                if (!lead || !lead.responsible_user_id) {
                    return;
                }

                var manager_id = lead.responsible_user_id;
                var $lead_card = $('.linked-form__field-value');

                // Добавляем мини-виджет с информацией о менеджере
                var manager_widget_html =
                    '<div class="salesbot-manager-widget" style="margin-top: 10px; padding: 10px; background: #f8f9fa; border-radius: 4px;">' +
                        '<div style="font-weight: 600; margin-bottom: 5px;">📊 Метрики менеджера</div>' +
                        '<iframe src="' + server_url + '/admin/manager/' + manager_id + '?compact=true" ' +
                            'style="width: 100%; height: 200px; border: none; border-radius: 4px;">' +
                        '</iframe>' +
                    '</div>';

                $lead_card.after(manager_widget_html);
            },

            destroy: function() {
                $('.salesbot-dashboard-container').remove();
                $('.salesbot-manager-widget').remove();
            },

            onSave: function() {
                return true;
            },

            dpSettings: function() {
                // Настройки виджета
                return true;
            }
        };

        return this;
    };

    return CustomWidget;
});
