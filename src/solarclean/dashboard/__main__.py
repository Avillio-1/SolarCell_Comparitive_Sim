import uvicorn


def main() -> None:
    # Runs from the repository root so configs/ and outputs/ resolve the same
    # way they do for the CLI. Reload is off on purpose: a reload mid-run would
    # kill an in-flight Monte Carlo job.
    uvicorn.run("solarclean.dashboard.app:app", host="127.0.0.1", port=8050)


if __name__ == "__main__":
    main()
