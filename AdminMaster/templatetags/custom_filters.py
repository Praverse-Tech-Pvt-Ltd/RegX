from django import template
register = template.Library()

@register.filter
def getattr_custom(form, base_name_or_counter):
    try:
        full_field_name = f"level_report_{base_name_or_counter}"
        field = form.fields.get(full_field_name)
        if field:
            return form[full_field_name]
        return ''
    except Exception as e:
        print(f"Exception: {e}")
        return ''