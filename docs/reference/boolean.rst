.. _boolean:

boolean    - boolean cut/intersect/stitch meshes
================================================

.. automodule:: madcad.boolean

most common
-----------

.. autofunction:: pierce

.. autofunction:: boolean


Those are shortcuts for `boolean`:

.. autofunction:: union

	.. image:: /screenshots/boolean-union.png
	
.. autofunction:: difference

	.. image:: /screenshots/boolean-difference.png

.. autofunction:: intersection

	.. image:: /screenshots/boolean-intersection.png

more advanced
-------------

.. autofunction:: cut_mesh
.. autofunction:: cut_web
.. autofunction:: cut_web_mesh
