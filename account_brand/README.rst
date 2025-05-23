=============
Account Brand
=============

.. 
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! This file is generated by oca-gen-addon-readme !!
   !! changes will be overwritten.                   !!
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
   !! source digest: sha256:70da6e15190815554bedb4fa3d814634a44bffdde655ccd4d09306080453377e
   !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

.. |badge1| image:: https://img.shields.io/badge/maturity-Beta-yellow.png
    :target: https://odoo-community.org/page/development-status
    :alt: Beta
.. |badge2| image:: https://img.shields.io/badge/licence-AGPL--3-blue.png
    :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
    :alt: License: AGPL-3
.. |badge3| image:: https://img.shields.io/badge/github-OCA%2Fbrand-lightgray.png?logo=github
    :target: https://github.com/OCA/brand/tree/18.0/account_brand
    :alt: OCA/brand
.. |badge4| image:: https://img.shields.io/badge/weblate-Translate%20me-F47D42.png
    :target: https://translation.odoo-community.org/projects/brand-18-0/brand-18-0-account_brand
    :alt: Translate me on Weblate
.. |badge5| image:: https://img.shields.io/badge/runboat-Try%20me-875A7B.png
    :target: https://runboat.odoo-community.org/builds?repo=OCA/brand&target_branch=18.0
    :alt: Try me on Runboat

|badge1| |badge2| |badge3| |badge4| |badge5|

This module allows you to send branded invoices to your customers. It
adds a brand field on the invoice and the brand information to the PDF
report.

**Table of contents**

.. contents::
   :local:

Configuration
=============

It is important to note that the "brand use level" **should** be set to
``Optional`` or ``Required``. The brand use level is configured in the
Users & Companies settings. By default it is set to 'Do not use brands
on business document'. Then the field to select a brand on the invoice
view will not be available.

To change the "brand use level":

#. Go to Settings > General Settings #. Select the brand use level, the
following options are available:
``Do not use brands on business document`` (Default) ``Optional``
``Required``

Usage
=====

To use this module, you need to:

1. Go to Accounting > Customers > Invoices
2. Select or create an invoice
3. Enter the information and select the brand
4. Print the PDF report. It includes the style and information of the
   brand.

To do point 4, the `Brand External Report
Layout <https://github.com/OCA/brand/tree/18.0/brand_external_report_layout/README.rst>`__
OCA module must be installed.

Bug Tracker
===========

Bugs are tracked on `GitHub Issues <https://github.com/OCA/brand/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us to smash it by providing a detailed and welcomed
`feedback <https://github.com/OCA/brand/issues/new?body=module:%20account_brand%0Aversion:%2018.0%0A%0A**Steps%20to%20reproduce**%0A-%20...%0A%0A**Current%20behavior**%0A%0A**Expected%20behavior**>`_.

Do not contact contributors directly about support or help with technical issues.

Credits
=======

Authors
-------

* Open Source Integrators
* ACSONE SA/NV

Contributors
------------

- Raphael Lee <rlee@opensourceintegrators.com>
- Steve Campbell <scampbell@opensourceintegrators.com>
- Maxime Chambreuil <mchambreuil@opensourceintegrators.com>
- `Obertix <https://www.obertix.net>`__:

  - Vicent Cubells

- Ammar Officewala <aofficewala@opensourceintegrators.com>
- bosd <<c5e2fd43-d292-4c90-9d1f-74ff3436329a@anonaddy.me>

Other credits
-------------

- Open Source Integrators <https://www.opensourceintegrators.com>

Maintainers
-----------

This module is maintained by the OCA.

.. image:: https://odoo-community.org/logo.png
   :alt: Odoo Community Association
   :target: https://odoo-community.org

OCA, or the Odoo Community Association, is a nonprofit organization whose
mission is to support the collaborative development of Odoo features and
promote its widespread use.

.. |maintainer-osi-scampbell| image:: https://github.com/osi-scampbell.png?size=40px
    :target: https://github.com/osi-scampbell
    :alt: osi-scampbell
.. |maintainer-sbejaoui| image:: https://github.com/sbejaoui.png?size=40px
    :target: https://github.com/sbejaoui
    :alt: sbejaoui

Current `maintainers <https://odoo-community.org/page/maintainer-role>`__:

|maintainer-osi-scampbell| |maintainer-sbejaoui| 

This module is part of the `OCA/brand <https://github.com/OCA/brand/tree/18.0/account_brand>`_ project on GitHub.

You are welcome to contribute. To learn how please visit https://odoo-community.org/page/Contribute.
