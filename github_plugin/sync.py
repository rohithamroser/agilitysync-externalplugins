from agilitysync.sync import (
    as_exceptions,
    BaseInbound,
    BaseOutbound,
    BasePayload,
    BaseEvent,
    BaseAttachmentUpload,
    FieldTypes,
    EventTypes,
    EventCategory
)
import re
from datetime import datetime
from dateutil import parser
import time
from external_plugins.github_integrate import transformer_functions


class Payload(BasePayload):

    def fetch_project(self, event):
        return "no_project"

    def fetch_asset(self, event):
        return event['ticket']["type"].lower()

    def is_cyclic_event(self, event, sync_user):
        return bool(event['user']['id'] == str(sync_user))


class Event(BaseEvent):

    def fetch_event_type(self):
        event_type = self.event['action']

        if event_type in ('ticket_created',):
            return EventTypes.CREATE
        elif event_type == 'ticket_deleted':
            return EventTypes.DELETE
        elif event_type in ('ticket_updated', 'comment_created'):
            return EventTypes.UPDATE

        error_msg = 'Unsupported event type [{}]'.format(event_type)
        raise as_exceptions.PayloadError(error_msg)

    def fetch_workitem_id(self):
        return self.event['ticket']['id']

    def fetch_workitem_display_id(self):
        return self.event['ticket']['id']

    def fetch_workitem_url(self):
        return "/".join(self.event['ticket']['url'].split("/")[1:])

    def fetch_revision(self):
        return self.event['ticket']['updated_at_with_timestamp']

    def fetch_timestamp(self):
        timestamp = parser.parse(self.event['ticket']["updated_at_with_timestamp"])

        return datetime.fromtimestamp(time.mktime(timestamp.utctimetuple())) # type: ignore


class Inbound(BaseInbound):
    def connect(self):
        try:
            return transformer_functions.connect(
                                                self.instance_details
            )
        except Exception as e:
            error_msg = 'Connection to Demo plugin failed.  Error is [{}].'.format(str(e))
            raise as_exceptions.InboundError(error_msg, stack_trace=True)

    def is_comment_updated(self, updated_at_with_time, latest_public_comment_html):
        updated_comment_epoch = datetime.strptime(updated_at_with_time, "%B %d, %Y at %H:%M").timestamp()
        search_pattern = datetime.fromtimestamp(updated_comment_epoch).strftime('%b %-d, %Y, %H:%M')
        found_pattern = re.search(search_pattern, latest_public_comment_html)
        if found_pattern:
            return True
        else:
            return False

    def fetch_event_category(self):
        category = []

        event_type = self.event["action"]

        if event_type in ('ticket_created', 'ticket_updated', 'ticket_deleted'):
            category.append(EventCategory.WORKITEM)

        if self.is_comment_updated(self.event["ticket"]["updated_at_with_time"], self.event["ticket"]["latest_public_comment_html"]):
            category.append(EventCategory.COMMENT)

            if "Attachment(s):" in self.event['ticket']['latest_comment_html']:
                category.append(EventCategory.ATTACHMENT)

        return category

    def fetch_comment(self):
        comment_data = ""
        if "latest_comment_html" in self.event["ticket"]:
            data = self.event['ticket']['latest_comment_html']
            data = data.replace("----------------------------------------------\n\n", "")
            data = data.split("Attachment(s):\n")
            comment_data = data[0]
        return comment_data


class Outbound(BaseOutbound):

    def connect(self):
        try:
            return transformer_functions.connect(
                                                self.instance_details
                                                )
        except Exception as e:
            error_msg = 'Connection to Demo plugin failed.  Error is [{}].'.format(str(e))
            raise as_exceptions.OutboundError(error_msg, stack_trace=True)

    def transform_fields(self, transfome_field_objs):
        create_fields = {}

        for outbound_field in transfome_field_objs:
            field_name = outbound_field.name

            if field_name in ["Assignee"]:  # Temp skip
                continue

            field_value = outbound_field.value
            create_fields[field_name.lower()] = field_value

        create_fields["type"] = self.asset_info["asset"]

        return create_fields

    def create(self, sync_fields):
        try:
            payload = {
                "ticket": sync_fields
            }

            ticket = transformer_functions.tickets(self.instance_object, payload=
                                                   payload)
            sync_info = {
                "project": ticket["external_id"],
                "issuetype": ticket["type"],
                "synced_fields": sync_fields
            }
            xref_object = {
                "relative_url": "/agent/tickets/{}".format(ticket["id"]),
                'id': str(ticket["id"]),
                'display_id': str(ticket["id"]),
                'sync_info': sync_info,
            }
            xref_object["absolute_url"] = "{}{}".format(
                self.instance_details["url"].rstrip("/"),
                xref_object["relative_url"])
            return xref_object

        except Exception as e:
            error_msg = ("Unable to create [{}] in Github. Error is [{}].\n Trying to sync fields \n"
                         "[{}]\n.".format(self.asset_info["display_name"], e, sync_fields))
            raise as_exceptions.OutboundError(error_msg, stack_trace=True)

    def update(self, sync_fields):
        try:
            payload = {
                "ticket": sync_fields
            }

            transformer_functions.tickets(self.instance_object,
                                          id=self.workitem_id, payload=payload)

        except Exception as e:
            error_msg = ('Unable to sync fields in Github. Error is [{}]. Trying to sync fields \n'
                         '[{} {}]\n.'.format(e, sync_fields['create_fields'], sync_fields['update_fields']))
            raise as_exceptions.OutboundError(error_msg, stack_trace=True)

    def comment_create(self, comment):
        try:
            payload = {
                "ticket": {
                    "comment": {
                        "body": comment
                    }
                }
            }

            transformer_functions.tickets(self.instance_object,
                                          id=self.workitem_id, payload=payload)
        except Exception as e:
            error_msg = 'Unable to sync comment. Error is [{}]. The comment is [{}]'.format(str(e), comment)
            raise as_exceptions.OutboundError(error_msg, stack_trace=True)
