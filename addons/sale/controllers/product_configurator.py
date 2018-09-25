# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from odoo import http, fields
from odoo.http import request


class ProductConfiguratorController(http.Controller):
    @http.route(['/product_configurator/configure'], type='json', auth="user", methods=['POST'])
    def configure(self, product_id, pricelist_id, **kw):
        product_template = request.env['product.template'].browse(int(product_id))
        to_currency = product_template.currency_id
        pricelist = self._get_pricelist(pricelist_id)
        if pricelist:
            product_template = product_template.with_context(pricelist=pricelist.id, partner=request.env.user.partner_id)
            to_currency = pricelist.currency_id

        return request.env['ir.ui.view'].render_template("sale.product_configurator_configure", {
            'product': product_template,
            'to_currency': to_currency,
            'pricelist': pricelist,
            'get_attribute_exclusions': self._get_attribute_exclusions
        })

    @http.route(['/product_configurator/show_optional_products'], type='json', auth="user", methods=['POST'])
    def show_optional_products(self, product_id, variant_values, pricelist_id, **kw):
        return self._show_optional_products(product_id, variant_values, self._get_pricelist(pricelist_id), False, **kw)

    @http.route(['/product_configurator/optional_product_items'], type='json', auth="user", methods=['POST'])
    def optional_product_items(self, product_id, pricelist_id, **kw):
        return self._optional_product_items(product_id, self._get_pricelist(pricelist_id), **kw)

    @http.route(['/product_configurator/get_combination_info'], type='json', auth="user", methods=['POST'])
    def get_combination_info(self, product_template_id, product_id, combination, add_qty, pricelist_id, **kw):
        return self._get_combination_info(product_template_id, product_id, combination, add_qty, self._get_pricelist(pricelist_id))

    def _optional_product_items(self, product_id, pricelist, **kw):
        product = request.env['product.product'].with_context(self._get_product_context(pricelist, **kw)).browse(int(product_id))
        to_currency = product.currency_id
        if pricelist:
            to_currency = pricelist.currency_id

        return request.env['ir.ui.view'].render_template("sale.optional_product_items", {
            'product': product,
            'reference_product': product,
            'pricelist': pricelist,
            'to_currency': to_currency,
            'get_attribute_exclusions': self._get_attribute_exclusions,
        })

    def _show_optional_products(self, product_id, variant_values, pricelist, handle_stock, **kw):
        product = request.env['product.product'].browse(int(product_id))
        from_currency = request.env.user.company_id.currency_id
        to_currency = pricelist.currency_id if pricelist else product.currency_id
        company = request.env['res.company'].browse(request.env.context.get('company_id')) or request.env['res.users']._get_company()
        date = request.env.context.get('date') or fields.Date.today()
        compute_currency = lambda price: from_currency._convert(price, to_currency, company, date)

        product = product.with_context(self._get_product_context(pricelist, **kw))

        has_optional_products = False
        for optional_product in product.optional_product_ids:
            if optional_product.get_filtered_variants(product):
                has_optional_products = True
                break

        if not has_optional_products:
            return False
        else:
            return request.env['ir.ui.view'].render_template("sale.optional_products_modal", {
                'product': product,
                'reference_product': product,
                'variant_values': variant_values,
                'pricelist': pricelist,
                'compute_currency': compute_currency,
                'to_currency': to_currency,
                'handle_stock': handle_stock,
                'get_attribute_exclusions': self._get_attribute_exclusions,
            })

    def _get_attribute_exclusions(self, product, reference_product=None):
        """ list of attribute exclusions of a product

        Args:
            - product (product.template): The base product template
            - reference_product (product.product): The reference product from which 'product' is an optional or accessory product

        :return: dict of exclusions
           exclusions.exclusions: exclusions within this product
           exclusions.parent_exclusions: exclusions coming from the reference_product
        """

        product_attribute_values = request.env['product.product.attribute.value'].search([
            ('product_tmpl_id', '=', product.id),
            ('product_attribute_value_id', 'in', product.attribute_line_ids.mapped('value_ids').ids),
        ])

        # array of all the excluded value_ids of all the filter lines for this product
        mapped_exclusions = {
            product_attribute_value.id: [
                value_id
                for filter_line in product_attribute_value.exclude_for.filtered(
                    lambda filter_line: filter_line.product_tmpl_id == product
                ) for value_id in filter_line.value_ids.ids
            ]
            for product_attribute_value in product_attribute_values
        }

        parent_exclusions = []
        if reference_product:
            parent_exclusions = [
                value_id
                for filter_line in reference_product.mapped('product_attribute_value_ids.exclude_for').filtered(
                    lambda filter_line: filter_line.product_tmpl_id == product
                ) for value_id in filter_line.value_ids.ids]

        return {
            'exclusions': mapped_exclusions,
            'parent_exclusions': parent_exclusions
        }

    def _get_product_context(self, pricelist=None, **kw):
        product_context = dict(request.context)
        if pricelist:
            if not product_context.get('pricelist'):
                product_context['pricelist'] = pricelist.id
            product_context.update(kw.get('kwargs', {}).get('context', {}))

        return product_context

    def _get_combination_info(self, product_template_id, product_id, combination, add_qty, pricelist, **kw):
        product_attribute_values = request.env['product.product.attribute.value'].browse(combination)
        filtered_product_attribute_values = product_attribute_values.filtered(
            lambda product_attribute_value: product_attribute_value.attribute_id.create_variant != 'never'
        )
        context = {
            'quantity': add_qty,
            'pricelist': pricelist.id if pricelist else None,
            'current_attributes_price_extra': [product_attribute_value.price_extra or 0.0 for product_attribute_value in product_attribute_values]
        }

        product_template = request.env['product.template'].with_context(context).browse(product_template_id)

        Product = request.env['product.product'].with_context(context)
        if product_id and not combination:
            product = Product.browse(product_id)
        else:
            products = Product.search([
                ('product_tmpl_id', '=', product_template_id)
            ])
            product = products.filtered(
                lambda product: all(product_attribute_value in product.product_attribute_value_ids
                    for product_attribute_value in filtered_product_attribute_values)
            )

        product_id = None
        list_price = product_template.price_compute('list_price')[product_template.id]
        price = product_template.price or list_price
        if(product):
            product = product.with_context(
                no_variant_attributes_price_extra=[product_attribute_value.price_extra or 0.0
                    for product_attribute_value in product_attribute_values.filtered(
                        lambda product_attribute_value: product_attribute_value.attribute_id.create_variant == 'never'
                    )
                ]
            )
            product_id = product.id
            list_price = product.price_compute('list_price')[product.id]
            price = product.price or list_price

        display_name = [product_template.name]
        if filtered_product_attribute_values:
            display_name.append(' (')
            display_name.append(', '.join(filtered_product_attribute_values.mapped('name')))
            display_name.append(')')

        if pricelist and pricelist.currency_id != product_template.currency_id:
            list_price = product_template.currency_id._convert(
                list_price, pricelist.currency_id,
                request.env.user.company_id, fields.Date.today()
            )

        return {
            'product_id': product_id,
            'product_template_id': product_template.id,
            'display_name': ''.join(display_name),
            'price': price,
            'list_price': list_price
        }

    def _get_pricelist(self, pricelist_id):
        return request.env['product.pricelist'].browse(int(pricelist_id)) if pricelist_id and pricelist_id != '0' else None
