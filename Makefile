


.PHONY: test coverage-report jupyter

jupyter:
	@echo "Installing kernel <pyqc> in jupyter"
	-yes | jupyter kernelspec uninstall pyqc
	poetry run python -m ipykernel install --user --name pyqc




test:
	poetry run coverage run -m pytest -sx --failed-first
	-rm coverage.svg
	poetry run coverage-badge -o coverage.svg

coverage-report: .coverage
	poetry run coverage html --omit="*/test*"
	open htmlcov/index.html

