import logging


def test_invalid_memory_dictionary_key_is_not_logged(client, caplog):
    private = 'owner-private-contact@example.test'
    with caplog.at_level(logging.WARNING, logger='app.requests'):
        response = client.post('/api/chat/validate', json={
            'conversation_id': 'validation-privacy', 'message': 'Help with bookkeeping',
            'memory': {'plans': {private: []}},
        })
    assert response.status_code == 422
    logged = '\n'.join(record.getMessage() for record in caplog.records)
    assert private not in logged
    assert 'body.memory.plans.<key>' in logged


def test_invalid_path_logs_route_template_instead_of_owner_value(client, caplog):
    private = 'PRIVATE_OWNER_PATH_' * 10
    from conftest import account_header
    with caplog.at_level(logging.WARNING, logger='app.requests'):
        response = client.put('/api/favourites/' + private, headers=account_header())
    assert response.status_code == 422
    logged = '\n'.join(record.getMessage() for record in caplog.records)
    assert private not in logged
    assert '/api/favourites/{tool_id}' in logged
