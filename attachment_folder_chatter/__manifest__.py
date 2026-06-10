{
    "name": "Attachment Folders in Chatter",
    "version": "18.0.1.8.0",
    "depends": ["base", "mail", "sale", "project"],
    "data": [
        "security/ir.model.access.csv",
        "views/attachment_folder_views.xml",
        "views/sale_order_views.xml",
        "views/project_task_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "attachment_folder_chatter/static/src/scss/attachment_folder_kanban.scss",
        ],
    },
    "installable": True,
    "application": False,
}
