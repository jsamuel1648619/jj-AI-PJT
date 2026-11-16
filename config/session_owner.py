import uuid


def session_owner(request, create=False):
    """Shared anonymous identity for all three features; never supplied by clients."""
    owner = request.session.get('diagnosis_owner', '')
    if not owner and create:
        owner = uuid.uuid4().hex
        request.session['diagnosis_owner'] = owner
    return owner
