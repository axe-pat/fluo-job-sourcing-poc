.PHONY: test test-python test-web refresh serve web

test: test-python test-web

test-python:
	python3 -W error::ResourceWarning -m unittest discover -s tests -v

test-web:
	cd web && npm test

refresh:
	python3 -m fluo refresh

serve:
	python3 -m fluo serve --no-auto-refresh

web:
	cd web && npm run dev
