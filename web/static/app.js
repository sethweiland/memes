/* Meme Pipeline Web App - Client JS */

// ---------------------------------------------------------------------------
// Polling helper
// ---------------------------------------------------------------------------

function pollJob(jobId, onProgress, onDone, onFailed, intervalMs) {
    intervalMs = intervalMs || 2000;
    var timer = setInterval(function() {
        fetch('/generate/api/status/' + jobId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.state === 'running' || data.state === 'pending') {
                    if (onProgress) onProgress(data.progress || 'Working...');
                } else if (data.state === 'done') {
                    clearInterval(timer);
                    if (onDone) onDone(data);
                } else if (data.state === 'failed') {
                    clearInterval(timer);
                    if (onFailed) onFailed(data.error || 'Unknown error');
                }
            })
            .catch(function(err) {
                console.error('Poll error:', err);
            });
    }, intervalMs);
    return timer;
}


// ---------------------------------------------------------------------------
// Start page
// ---------------------------------------------------------------------------

function initStartPage() {
    var form = document.getElementById('start-form');
    var topicInput = document.getElementById('topic-input');
    var surpriseBtn = document.getElementById('surprise-btn');
    var advToggle = document.getElementById('adv-toggle');
    var advContent = document.getElementById('adv-content');
    var contextBtns = document.getElementById('context-mode-btns');
    var contextHint = document.getElementById('context-hint');
    var domainIndicator = document.getElementById('domain-indicator');
    var domainName = document.getElementById('domain-name');
    var useWebBtn = document.getElementById('use-web-btn');
    var domainSelect = document.getElementById('domain-select');
    var domainHint = document.getElementById('domain-hint');
    var topicRadar = document.getElementById('topic-radar');
    var topicRadarGrid = document.getElementById('topic-radar-grid');
    var topicRadarSubtitle = document.getElementById('topic-radar-subtitle');
    var refreshRadarBtn = document.getElementById('refresh-radar-btn');

    var currentContextMode = 'none';
    var domainSummaries = {};

    function renderTopicRadar(topics) {
        if (!topicRadar || !topicRadarGrid) return;
        topicRadarGrid.innerHTML = '';
        if (!topics || !topics.length) {
            topicRadar.style.display = 'none';
            return;
        }
        topicRadar.style.display = 'block';
        topics.slice(0, 12).forEach(function(item) {
            var card = document.createElement('button');
            card.type = 'button';
            card.className = 'topic-card';
            card.innerHTML = ''
                + '<span class="topic-lane">' + escapeHtml((item.lane || '').replace(/_/g, ' ')) + '</span>'
                + '<strong>' + escapeHtml(item.topic || '') + '</strong>'
                + '<span class="topic-angle">' + escapeHtml(item.meme_angle || '') + '</span>'
                + '<span class="topic-score">Score ' + escapeHtml(String(item.overall_score || '')) + ' · ' + escapeHtml(item.source || '') + '</span>';
            card.addEventListener('click', function() {
                if (topicInput) {
                    topicInput.value = item.topic || '';
                    topicInput.focus();
                }
                if (domainSelect && domainSelect.value) {
                    currentContextMode = 'rag';
                }
            });
            topicRadarGrid.appendChild(card);
        });
    }

    function loadTopicRadar(domainName) {
        if (!domainName || !topicRadar || !topicRadarGrid) {
            if (topicRadar) topicRadar.style.display = 'none';
            return;
        }
        topicRadar.style.display = 'block';
        topicRadarGrid.innerHTML = '<div class="topic-radar-loading">Scanning topic lanes...</div>';
        var summary = domainSummaries[domainName];
        if (topicRadarSubtitle) {
            topicRadarSubtitle.textContent = summary
                ? 'Fresh candidate topics for ' + summary.display_name + '.'
                : 'Fresh candidate topics for this domain pack.';
        }
        fetch('/generate/api/topic-radar?domain=' + encodeURIComponent(domainName) + '&limit=18&news=0')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.error) {
                    topicRadarGrid.innerHTML = '<div class="topic-radar-loading">' + escapeHtml(data.error) + '</div>';
                    return;
                }
                renderTopicRadar(data.topics || []);
            })
            .catch(function(err) {
                topicRadarGrid.innerHTML = '<div class="topic-radar-loading">Radar unavailable: ' + escapeHtml(String(err)) + '</div>';
            });
    }

    // Context mode hints
    var contextHints = {
        auto: 'Auto-detects if a knowledge base matches your topic.',
        web: 'Uses web search to find relevant context for any topic.',
        none: 'Uses only xAI/Grok generation and avoids OpenAI-backed archive search.',
    };

    // Context mode toggle
    if (contextBtns) {
        contextBtns.querySelectorAll('.context-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                contextBtns.querySelectorAll('.context-btn').forEach(function(b) {
                    b.classList.remove('active');
                });
                btn.classList.add('active');
                currentContextMode = btn.dataset.mode;
                if (contextHint) {
                    contextHint.textContent = contextHints[currentContextMode] || '';
                }
                // Hide domain indicator when switching away from auto
                if (domainIndicator && currentContextMode !== 'auto') {
                    domainIndicator.style.display = 'none';
                }
            });
        });
    }

    if (domainSelect) {
        fetch('/generate/api/domains')
            .then(function(r) { return r.json(); })
            .then(function(data) {
                (data.domains || []).forEach(function(domain) {
                    domainSummaries[domain.name] = domain;
                    var option = document.createElement('option');
                    option.value = domain.name;
                    option.textContent = domain.display_name || domain.name;
                    domainSelect.appendChild(option);
                });
            })
            .catch(function(err) {
                console.warn('Failed to load domain packs:', err);
            });

        domainSelect.addEventListener('change', function() {
            var selected = domainSelect.value;
            if (selected && contextBtns) {
                currentContextMode = 'rag';
                contextBtns.querySelectorAll('.context-btn').forEach(function(b) {
                    b.classList.toggle('active', b.dataset.mode === 'auto');
                });
                if (contextHint) {
                    contextHint.textContent = 'Uses the selected domain pack knowledge base and tone rules.';
                }
            }
            if (domainHint) {
                var summary = domainSummaries[selected];
                domainHint.textContent = summary
                    ? summary.description + ' Source: ' + summary.content_source_name + '.'
                    : 'Use Generic for any topic, or choose a niche pack when one exists.';
            }
            loadTopicRadar(selected);
        });
    }

    if (refreshRadarBtn && domainSelect) {
        refreshRadarBtn.addEventListener('click', function() {
            loadTopicRadar(domainSelect.value);
        });
    }

    // "Use web instead" button in domain indicator
    if (useWebBtn) {
        useWebBtn.addEventListener('click', function(e) {
            e.preventDefault();
            currentContextMode = 'web';
            if (contextBtns) {
                contextBtns.querySelectorAll('.context-btn').forEach(function(b) {
                    b.classList.remove('active');
                    if (b.dataset.mode === 'web') b.classList.add('active');
                });
            }
            if (contextHint) {
                contextHint.textContent = contextHints.web;
            }
            if (domainIndicator) {
                domainIndicator.style.display = 'none';
            }
        });
    }

    // Advanced toggle
    if (advToggle && advContent) {
        advToggle.addEventListener('click', function() {
            advContent.classList.toggle('show');
            advToggle.textContent = advContent.classList.contains('show')
                ? 'Hide advanced options' : 'Show advanced options';
        });
    }

    // Slider value display
    document.querySelectorAll('input[type="range"]').forEach(function(slider) {
        var display = document.getElementById(slider.id + '-val');
        if (display) {
            slider.addEventListener('input', function() { display.textContent = slider.value; });
        }
    });

    // Surprise me
    if (surpriseBtn) {
        surpriseBtn.addEventListener('click', function() {
            surpriseBtn.disabled = true;
            surpriseBtn.textContent = 'Thinking...';
            fetch('/generate/api/surprise', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ domain: domainSelect ? domainSelect.value : '' }),
            })
                .then(function(r) { return r.json(); })
                .then(function(data) {
                    if (data.topic) topicInput.value = data.topic;
                    else alert(data.error || 'Failed to generate topic');
                })
                .catch(function(err) { alert('Error: ' + err); })
                .finally(function() {
                    surpriseBtn.disabled = false;
                    surpriseBtn.textContent = 'Surprise me';
                });
        });
    }

    // Form submit
    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var topic = topicInput.value.trim();
            if (!topic) { topicInput.focus(); return; }

            var numConcepts = document.getElementById('num-concepts');
            var creativity = document.getElementById('creativity');
            var humorEdge = document.getElementById('humor-edge');
            var modelSelect = document.getElementById('model-select');
            var aiRefine = document.getElementById('ai-refine');
            var criticModelSelect = document.getElementById('critic-model-select');
            var selectedDomain = domainSelect ? domainSelect.value : '';

            var body = {
                topic: topic,
                num_concepts: numConcepts ? parseInt(numConcepts.value) : 20,
                creativity: creativity ? parseFloat(creativity.value) / 10 : 1.0,
                humor_edge: humorEdge ? parseInt(humorEdge.value) : 7,
                context_mode: currentContextMode,
                domain: selectedDomain,
                model: modelSelect ? modelSelect.value : 'gpt-5.4-mini',
                ai_refine: aiRefine ? aiRefine.checked : false,
                critic_model: criticModelSelect ? criticModelSelect.value : 'gpt-5.5',
            };

            var submitBtn = form.querySelector('button[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Starting...';

            fetch('/generate/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.job_id) {
                    window.location.href = '/generate/review/' + data.job_id;
                } else {
                    alert(data.error || 'Failed to start');
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Generate';
                }
            })
            .catch(function(err) {
                alert('Error: ' + err);
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate';
            });
        });
    }
}


// ---------------------------------------------------------------------------
// Review page
// ---------------------------------------------------------------------------

function buildStarRating(index, prefix) {
    var html = '<div class="star-rating" data-index="' + index + '" data-prefix="' + prefix + '">';
    for (var s = 1; s <= 5; s++) {
        html += '<span class="star" data-value="' + s + '">&#9733;</span>';
    }
    html += '</div>';
    return html;
}

function buildFeedbackInput(index, prefix) {
    return '<textarea class="feedback-input" data-index="' + index + '" data-prefix="' + prefix +
           '" placeholder="What works or doesn\'t? (optional)"></textarea>';
}

function attachFeedbackHandlers(container, feedbackData, prefix) {
    container.querySelectorAll('.star-rating[data-prefix="' + prefix + '"]').forEach(function(row) {
        var idx = row.dataset.index;
        row.querySelectorAll('.star').forEach(function(star) {
            star.addEventListener('click', function(e) {
                e.stopPropagation();
                var val = parseInt(star.dataset.value);
                if (!feedbackData[idx]) feedbackData[idx] = {};
                feedbackData[idx].rating = val;
                // Update visual state
                row.querySelectorAll('.star').forEach(function(s) {
                    s.classList.toggle('active', parseInt(s.dataset.value) <= val);
                });
            });
        });
    });
    container.querySelectorAll('.feedback-input[data-prefix="' + prefix + '"]').forEach(function(ta) {
        ta.addEventListener('click', function(e) { e.stopPropagation(); });
        ta.addEventListener('input', function(e) {
            var idx = ta.dataset.index;
            if (!feedbackData[idx]) feedbackData[idx] = {};
            feedbackData[idx].feedback = ta.value;
        });
    });
}

function collectFeedbackMemes(evaluated, selectedIndices, feedbackData) {
    var memes = [];
    (evaluated || []).forEach(function(meme) {
        var idx = String(meme.index);
        var fb = feedbackData[idx] || {};
        if (fb.rating == null && !fb.feedback) return;
        memes.push({
            index: meme.index,
            format: meme.format,
            top_text: meme.top_text,
            bottom_text: meme.bottom_text,
            scores: meme.scores,
            overall_score: meme.overall_score,
            selected: selectedIndices ? selectedIndices.has(meme.index) : false,
            user_rating: fb.rating || null,
            user_feedback: fb.feedback || '',
        });
    });
    return memes;
}

function postFeedback(sessionId, topic, stage, memes) {
    return fetch('/generate/api/feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            session_id: sessionId,
            topic: topic,
            stage: stage,
            memes: memes,
        }),
    });
}


function initReviewPage(jobId) {
    var progressBox = document.getElementById('progress-box');
    var progressText = document.getElementById('progress-text');
    var cardsContainer = document.getElementById('cards-container');
    var selectionBar = document.getElementById('selection-bar');
    var selectionCount = document.getElementById('selection-count');
    var generateBtn = document.getElementById('generate-selected-btn');

    var selectedIndices = new Set();
    var feedbackData = {};
    var currentEvaluated = null;
    var currentTopic = '';

    // Start polling
    pollJob(jobId,
        function onProgress(msg) {
            if (progressText) progressText.textContent = msg;
        },
        function onDone(data) {
            if (progressBox) progressBox.style.display = 'none';
            renderMemeCards(data);
        },
        function onFailed(err) {
            if (progressBox) {
                progressBox.innerHTML = '<div class="error-box"><h2>Generation Failed</h2><p>' +
                    escapeHtml(err) + '</p><a href="/generate/" class="btn btn-primary" style="margin-top:12px;">Try Again</a></div>';
            }
        }
    );

    function renderMemeCards(data) {
        if (!data.evaluated || !data.evaluated.length) {
            cardsContainer.innerHTML = '<div class="empty">No memes were generated. Try a different topic.</div>';
            return;
        }

        currentEvaluated = data.evaluated;
        currentTopic = data.topic || '';

        var criteria = data.domain_criteria || [];
        var html = '<h2>Review ' + data.evaluated.length + ' memes for "' + escapeHtml(data.topic || '') + '"</h2>';
        html += '<p style="color:#666;margin-bottom:20px;">Click cards to select, then generate images for your picks.</p>';
        if (data.creative_brief) {
            html += '<details class="creative-brief"><summary>Creative Brief</summary><pre>' +
                escapeHtml(data.creative_brief) + '</pre></details>';
        }
        if (data.ai_critique) {
            var critiqueText = '';
            if (data.ai_critique.rewrite_brief) {
                critiqueText += 'Rewrite brief: ' + data.ai_critique.rewrite_brief + '\n\n';
            }
            if (data.ai_critique.prompt_rules && data.ai_critique.prompt_rules.length) {
                critiqueText += 'Prompt rules:\n';
                data.ai_critique.prompt_rules.forEach(function(rule) {
                    critiqueText += '- ' + rule + '\n';
                });
            }
            html += '<details class="creative-brief ai-critique"><summary>AI Critic Loop</summary><pre>' +
                escapeHtml(critiqueText.trim()) + '</pre></details>';
        }
        if (data.ai_critique_error) {
            html += '<div class="warning-box">AI critic loop failed: ' +
                escapeHtml(data.ai_critique_error) + '</div>';
        }

        data.evaluated.forEach(function(meme) {
            html += buildMemeCard(meme, criteria);
        });

        cardsContainer.innerHTML = html;

        selectedIndices = new Set(data.recommended_indices || []);
        selectedIndices.forEach(function(idx) {
            var card = cardsContainer.querySelector('.meme-card[data-index="' + idx + '"]');
            if (card) card.classList.add('selected');
        });
        updateSelectionBar();

        // Attach click handlers
        cardsContainer.querySelectorAll('.meme-card').forEach(function(card) {
            card.addEventListener('click', function() {
                var idx = parseInt(card.dataset.index);
                if (selectedIndices.has(idx)) {
                    selectedIndices.delete(idx);
                    card.classList.remove('selected');
                } else {
                    selectedIndices.add(idx);
                    card.classList.add('selected');
                }
                updateSelectionBar();
            });
        });

        // Attach feedback handlers
        attachFeedbackHandlers(cardsContainer, feedbackData, 'review');
    }

    function buildMemeCard(meme, criteria) {
        var html = '<div class="meme-card" data-index="' + meme.index + '">';
        html += '<div class="rank">' + meme.index + '</div>';
        html += '<div class="check">&#10003;</div>';
        html += '<div class="meme-content">';
        html += '<h3>' + escapeHtml(meme.format);
        if (meme.generation_source === 'critic_rewrite') {
            html += ' <span class="source-badge source-critic" title="Generated by the AI critic rewrite pass">AI rewrite</span>';
        }
        // Template category badge
        if (meme.template_category) {
            var badges = {
                'trending': '<span class="template-badge badge-trending" title="Trending this month">🔥</span>',
                'new': '<span class="template-badge badge-new" title="New template">✨</span>',
                'classic': '<span class="template-badge badge-classic" title="All-time classic">👑</span>'
            };
            html += ' ' + (badges[meme.template_category] || '');
        }
        html += '</h3>';
        html += '<div class="meme-text"><strong>Top:</strong> ' + escapeHtml(meme.top_text) + '</div>';
        html += '<div class="meme-text"><strong>Bottom:</strong> ' + escapeHtml(meme.bottom_text) + '</div>';

        // Score bars
        html += '<div style="margin-top:10px;">';
        criteria.forEach(function(crit) {
            var score = meme.scores[crit.name] || 0;
            var cls = score >= 7 ? 'high' : (score >= 4 ? 'mid' : 'low');
            html += '<div class="score-row">';
            html += '<span class="score-label">' + escapeHtml(crit.display_name) + '</span>';
            html += '<div class="score-bar-bg"><div class="score-bar ' + cls + '" style="width:' + (score * 10) + '%"></div></div>';
            html += '<span class="score-value">' + score + '</span>';
            html += '</div>';
        });
        // Overall
        var overallCls = meme.overall_score >= 7 ? 'high' : (meme.overall_score >= 4 ? 'mid' : 'low');
        html += '<div class="score-row" style="margin-top:4px;font-weight:600;">';
        html += '<span class="score-label">Overall</span>';
        html += '<div class="score-bar-bg"><div class="score-bar ' + overallCls + '" style="width:' + (meme.overall_score * 10) + '%"></div></div>';
        html += '<span class="score-value">' + meme.overall_score + '</span>';
        html += '</div>';
        html += '</div>';

        if (meme.is_absurdist) {
            html += '<span class="absurdist-badge">Intentional Absurdism?</span>';
        }
        if (meme.evaluation_notes) {
            html += '<div class="eval-notes">' + escapeHtml(meme.evaluation_notes) + '</div>';
        }

        // Feedback: star rating + textarea
        html += '<div class="feedback-section">';
        html += buildStarRating(meme.index, 'review');
        html += buildFeedbackInput(meme.index, 'review');
        html += '</div>';

        html += '</div></div>';
        return html;
    }

    function updateSelectionBar() {
        var count = selectedIndices.size;
        if (selectionCount) selectionCount.textContent = count + ' selected';
        if (selectionBar) {
            if (count > 0) selectionBar.classList.add('show');
            else selectionBar.classList.remove('show');
        }
    }

    // Generate selected — save feedback first, then finalize
    if (generateBtn) {
        generateBtn.addEventListener('click', function() {
            if (selectedIndices.size === 0) return;
            generateBtn.disabled = true;
            generateBtn.textContent = 'Starting...';

            // Collect and send review-stage feedback
            var memes = collectFeedbackMemes(currentEvaluated, selectedIndices, feedbackData);
            var feedbackPromise = memes.length > 0
                ? postFeedback(jobId, currentTopic, 'review', memes)
                : Promise.resolve();

            feedbackPromise.then(function() {
                return fetch('/generate/api/finalize', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        job_id: jobId,
                        selected_indices: Array.from(selectedIndices),
                    }),
                });
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.job_id) {
                    window.location.href = '/generate/results/' + data.job_id;
                } else {
                    alert(data.error || 'Failed to start finalization');
                    generateBtn.disabled = false;
                    generateBtn.textContent = 'Generate Selected';
                }
            })
            .catch(function(err) {
                alert('Error: ' + err);
                generateBtn.disabled = false;
                generateBtn.textContent = 'Generate Selected';
            });
        });
    }
}


// ---------------------------------------------------------------------------
// Results page
// ---------------------------------------------------------------------------

function initResultsPage(jobId) {
    var progressBox = document.getElementById('progress-box');
    var progressText = document.getElementById('progress-text');
    var resultsContainer = document.getElementById('results-container');
    var resultsFeedbackData = {};
    var currentImages = null;

    pollJob(jobId,
        function onProgress(msg) {
            if (progressText) progressText.textContent = msg;
        },
        function onDone(data) {
            if (progressBox) progressBox.style.display = 'none';
            renderResults(data);
        },
        function onFailed(err) {
            if (progressBox) {
                progressBox.innerHTML = '<div class="error-box"><h2>Image Generation Failed</h2><p>' +
                    escapeHtml(err) + '</p><a href="/generate/" class="btn btn-primary" style="margin-top:12px;">Try Again</a></div>';
            }
        }
    );

    function renderResults(data) {
        if (!data.images || !data.images.length) {
            resultsContainer.innerHTML = '<div class="empty">No images were generated.</div>';
            return;
        }

        currentImages = data.images;

        var html = '<h2>' + data.images.length + ' Memes Generated</h2>';
        html += '<div class="results-grid">';
        data.images.forEach(function(img, i) {
            html += '<div class="result-card">';
            if (img.filename) {
                html += '<img src="/gallery/image/' + encodeURIComponent(img.filename) + '" alt="' + escapeHtml(img.template) + '">';
            }
            html += '<div class="result-info">';
            html += '<h3>' + escapeHtml(img.template) + '</h3>';
            html += '<div class="meme-text"><strong>Top:</strong> ' + escapeHtml(img.top_text) + '</div>';
            html += '<div class="meme-text"><strong>Bottom:</strong> ' + escapeHtml(img.bottom_text) + '</div>';
            if (img.caption) {
                html += '<div class="caption">' + escapeHtml(img.caption) + '</div>';
                html += '<button class="btn btn-secondary copy-btn" data-caption="' + escapeAttr(img.caption) + '">Copy Caption</button>';
            }
            if (img.filename) {
                html += '<div class="download-btns">';
                html += '<button class="btn btn-instagram" onclick="showInstagramModalFromResults(event, \'' + escapeAttr(img.filename) + '\', \'' + escapeAttr(img.caption || '') + '\');">📸 Post to Instagram</button>';
                html += '<a class="btn btn-download" href="/gallery/download/' + encodeURIComponent(img.filename) + '" download>&#8595; Download</a>';
                html += '<a class="btn btn-download btn-download-ig" href="/gallery/download/' + encodeURIComponent(img.filename) + '?format=instagram" download>&#8595; Download for IG</a>';
                html += '</div>';
            }
            // Feedback: star rating + textarea
            html += '<div class="feedback-section">';
            html += buildStarRating(i, 'results');
            html += buildFeedbackInput(i, 'results');
            html += '</div>';
            html += '</div></div>';
        });
        html += '</div>';

        // Topic feedback
        html += '<div style="text-align:center;margin-top:24px;max-width:500px;margin-left:auto;margin-right:auto;">';
        html += '<label for="topic-notes" style="display:block;margin-bottom:6px;font-weight:600;color:#555;">Any topics you\'re tired of seeing?</label>';
        html += '<textarea id="topic-notes" style="width:100%;padding:8px;border:1px solid #ccc;border-radius:6px;font-size:14px;resize:vertical;min-height:40px;" placeholder="e.g. &quot;Too many Bill Monroe memes, more banjo jokes please&quot;"></textarea>';
        html += '</div>';

        // Save Feedback button
        html += '<div style="text-align:center;margin-top:24px;">';
        html += '<button class="btn btn-primary save-feedback-btn" id="save-results-feedback">Save Feedback</button>';
        html += '</div>';

        resultsContainer.innerHTML = html;

        // Copy caption buttons
        resultsContainer.querySelectorAll('.copy-btn').forEach(function(btn) {
            btn.addEventListener('click', function() {
                var text = btn.dataset.caption;
                navigator.clipboard.writeText(text).then(function() {
                    btn.textContent = 'Copied!';
                    btn.classList.add('copied');
                    setTimeout(function() {
                        btn.textContent = 'Copy Caption';
                        btn.classList.remove('copied');
                    }, 2000);
                });
            });
        });

        // Attach feedback handlers
        attachFeedbackHandlers(resultsContainer, resultsFeedbackData, 'results');

        // Save Feedback button handler
        var saveBtn = document.getElementById('save-results-feedback');
        if (saveBtn) {
            saveBtn.addEventListener('click', function() {
                var memes = [];
                (currentImages || []).forEach(function(img, i) {
                    var fb = resultsFeedbackData[String(i)] || {};
                    if (fb.rating == null && !fb.feedback) return;
                    memes.push({
                        format: img.template,
                        top_text: img.top_text,
                        bottom_text: img.bottom_text,
                        filename: img.filename || null,
                        caption: img.caption || '',
                        user_rating: fb.rating || null,
                        user_feedback: fb.feedback || '',
                    });
                });
                // Attach topic notes to each meme entry if provided
                var topicNotesEl = document.getElementById('topic-notes');
                var topicNotes = topicNotesEl ? topicNotesEl.value.trim() : '';
                if (topicNotes) {
                    memes.forEach(function(m) { m.topic_notes = topicNotes; });
                }

                if (memes.length === 0 && !topicNotes) {
                    alert('Rate at least one meme or add topic notes before saving.');
                    return;
                }
                // If only topic notes but no meme ratings, create a placeholder entry
                if (memes.length === 0 && topicNotes) {
                    memes.push({ topic_notes: topicNotes });
                }
                saveBtn.disabled = true;
                saveBtn.textContent = 'Saving...';
                postFeedback(jobId, '', 'results', memes)
                    .then(function(r) {
                        if (!r.ok) {
                            return r.json().catch(function() { return {}; }).then(function(body) {
                                throw new Error(body.error || 'Server error ' + r.status);
                            });
                        }
                        return r.json();
                    })
                    .then(function() {
                        saveBtn.textContent = 'Saved!';
                        saveBtn.classList.add('copied');
                        setTimeout(function() {
                            saveBtn.textContent = 'Save Feedback';
                            saveBtn.classList.remove('copied');
                            saveBtn.disabled = false;
                        }, 2000);
                    })
                    .catch(function(err) {
                        alert('Failed to save feedback: ' + (err.message || err));
                        saveBtn.disabled = false;
                        saveBtn.textContent = 'Save Feedback';
                    });
            });
        }
    }
}


// ---------------------------------------------------------------------------
// Gallery lightbox
// ---------------------------------------------------------------------------

function initGalleryLightbox() {
    var lightbox = document.getElementById('lightbox');
    var lightboxImg = document.getElementById('lightbox-img');
    if (!lightbox) return;

    document.querySelectorAll('.gallery-item').forEach(function(item) {
        item.addEventListener('click', function() {
            var src = item.querySelector('img').src;
            lightboxImg.src = src;
            lightbox.classList.add('show');
        });
    });

    lightbox.addEventListener('click', function(e) {
        if (e.target !== lightboxImg) {
            lightbox.classList.remove('show');
        }
    });

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') lightbox.classList.remove('show');
    });
}


// ---------------------------------------------------------------------------
// Instagram Publishing
// ---------------------------------------------------------------------------

var currentInstagramFilename = '';

function showInstagramModal(event, filename, caption) {
    event.stopPropagation();
    event.preventDefault();
    
    var modal = document.getElementById('instagram-modal');
    var previewImg = document.getElementById('instagram-preview-img');
    var captionTextarea = document.getElementById('instagram-caption');
    var imageUrlInput = document.getElementById('instagram-image-url');
    var statusDiv = document.getElementById('instagram-status');
    
    if (!modal) return;
    
    currentInstagramFilename = filename;
    previewImg.src = '/gallery/image/' + encodeURIComponent(filename);
    captionTextarea.value = caption || '';
    imageUrlInput.value = '';
    statusDiv.innerHTML = '';
    
    modal.style.display = 'block';
}

function closeInstagramModal() {
    var modal = document.getElementById('instagram-modal');
    if (modal) modal.style.display = 'none';
    currentInstagramFilename = '';
}

function showInstagramModalFromResults(event, filename, caption) {
    event.stopPropagation();
    event.preventDefault();
    showInstagramModal(event, filename, caption);
}

function publishToInstagram() {
    var captionTextarea = document.getElementById('instagram-caption');
    var imageUrlInput = document.getElementById('instagram-image-url');
    var postBtn = document.getElementById('instagram-post-btn');
    var statusDiv = document.getElementById('instagram-status');
    
    var caption = captionTextarea.value.trim();
    var imageUrl = imageUrlInput.value.trim();
    
    if (!caption) {
        statusDiv.innerHTML = '<div class="error-box">Caption is required</div>';
        return;
    }
    
    if (imageUrl && !imageUrl.startsWith('http://') && !imageUrl.startsWith('https://')) {
        statusDiv.innerHTML = '<div class="error-box">Image URL must start with http:// or https://</div>';
        return;
    }
    
    postBtn.disabled = true;
    postBtn.textContent = 'Publishing...';
    
    var statusMessage = imageUrl 
        ? '<div class="info-box">Creating Instagram post...</div>'
        : '<div class="info-box">Uploading to S3, then creating Instagram post...</div>';
    statusDiv.innerHTML = statusMessage;
    
    // Try both endpoints (generate and gallery have the same API)
    var endpoint = window.location.pathname.includes('/generate/')
        ? '/generate/api/instagram/publish'
        : '/gallery/api/instagram/publish';
    
    fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            public_image_url: imageUrl,
            caption: caption,
            filename: currentInstagramFilename,
        }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.success) {
            statusDiv.innerHTML = '<div class="success-box">✅ Successfully posted to Instagram!<br>' +
                (data.permalink ? '<a href="' + escapeAttr(data.permalink) + '" target="_blank">View on Instagram</a>' : '') +
                '</div>';
            postBtn.textContent = 'Posted!';
            setTimeout(function() {
                closeInstagramModal();
            }, 3000);
        } else {
            statusDiv.innerHTML = '<div class="error-box">❌ Failed to post: ' + escapeHtml(data.error || 'Unknown error') + '</div>';
            postBtn.disabled = false;
            postBtn.textContent = 'Post to Instagram';
        }
    })
    .catch(function(err) {
        statusDiv.innerHTML = '<div class="error-box">❌ Request failed: ' + escapeHtml(String(err)) + '</div>';
        postBtn.disabled = false;
        postBtn.textContent = 'Post to Instagram';
    });
}

// Close modal when clicking the X or outside
document.addEventListener('DOMContentLoaded', function() {
    var modal = document.getElementById('instagram-modal');
    if (!modal) return;
    
    var closeBtn = modal.querySelector('.instagram-modal-close');
    if (closeBtn) {
        closeBtn.addEventListener('click', closeInstagramModal);
    }
    
    window.addEventListener('click', function(e) {
        if (e.target === modal) {
            closeInstagramModal();
        }
    });
    
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal.style.display === 'block') {
            closeInstagramModal();
        }
    });
});


// ---------------------------------------------------------------------------
// Template review (migrated doAction / unapprove)
// ---------------------------------------------------------------------------

function doAction(templateId, action, cardEl) {
    var url = '/templates/api/' + action + '/' + templateId;
    var body = {};
    if (action === 'approve') {
        var ta = cardEl.querySelector('textarea');
        if (ta) body.description = ta.value;
    }
    var btns = cardEl.querySelectorAll('.btn');
    btns.forEach(function(b) { b.disabled = true; });
    fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          if (data.ok) {
              cardEl.classList.add('fade-out');
              setTimeout(function() { cardEl.remove(); updateReviewCounter(); }, 300);
          } else {
              alert('Error: ' + (data.error || 'unknown'));
              btns.forEach(function(b) { b.disabled = false; });
          }
      }).catch(function(err) {
          alert('Request failed: ' + err);
          btns.forEach(function(b) { b.disabled = false; });
      });
}

function unapproveTemplate(templateId, cardEl) {
    var btns = cardEl.querySelectorAll('.btn');
    btns.forEach(function(b) { b.disabled = true; });
    fetch('/templates/api/unapprove/' + templateId, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
    }).then(function(r) { return r.json(); })
      .then(function(data) {
          if (data.ok) {
              cardEl.classList.add('fade-out');
              setTimeout(function() { cardEl.remove(); }, 300);
          } else {
              alert('Error: ' + (data.error || 'unknown'));
              btns.forEach(function(b) { b.disabled = false; });
          }
      });
}

function updateReviewCounter() {
    var counter = document.getElementById('counter');
    if (!counter) return;
    var cards = document.querySelectorAll('.card:not(.fade-out)');
    var total = parseInt(counter.dataset.total || '0');
    var remaining = cards.length;
    counter.textContent = (total - remaining) + ' of ' + total + ' reviewed';
}


// ---------------------------------------------------------------------------
// Utilities
// ---------------------------------------------------------------------------

function escapeHtml(text) {
    if (!text) return '';
    var el = document.createElement('span');
    el.textContent = text;
    return el.innerHTML;
}

function escapeAttr(text) {
    if (!text) return '';
    return text.replace(/&/g, '&amp;').replace(/"/g, '&quot;')
               .replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}


// ---------------------------------------------------------------------------
// Video polling helper
// ---------------------------------------------------------------------------

function pollVideoJob(jobId, onProgress, onDone, onFailed, intervalMs) {
    intervalMs = intervalMs || 3000;
    var timer = setInterval(function() {
        fetch('/video/api/status/' + jobId)
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.state === 'running' || data.state === 'pending') {
                    if (onProgress) onProgress(data.progress || 'Working...');
                } else if (data.state === 'done') {
                    clearInterval(timer);
                    if (onDone) onDone(data);
                } else if (data.state === 'failed') {
                    clearInterval(timer);
                    if (onFailed) onFailed(data.error || 'Unknown error');
                }
            })
            .catch(function(err) {
                console.error('Poll error:', err);
            });
    }, intervalMs);
    return timer;
}


// ---------------------------------------------------------------------------
// Video Start page
// ---------------------------------------------------------------------------

function initVideoStartPage() {
    var form = document.getElementById('video-start-form');
    var topicInput = document.getElementById('topic-input');
    var advToggle = document.getElementById('adv-toggle');
    var advContent = document.getElementById('adv-content');

    // Advanced toggle
    if (advToggle && advContent) {
        advToggle.addEventListener('click', function() {
            advContent.classList.toggle('show');
            advToggle.textContent = advContent.classList.contains('show')
                ? 'Hide advanced options' : 'Show advanced options';
        });
    }

    // Slider value displays
    document.querySelectorAll('input[type="range"]').forEach(function(slider) {
        var display = document.getElementById(slider.id + '-val');
        if (display) {
            slider.addEventListener('input', function() { display.textContent = slider.value; });
        }
    });

    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            var topic = topicInput.value.trim();
            if (!topic) { topicInput.focus(); return; }

            var body = {
                topic: topic,
                num_concepts: parseInt(document.getElementById('num-concepts').value) || 10,
                num_scenes: parseInt(document.getElementById('num-scenes').value) || 2,
                target_duration: parseFloat(document.getElementById('target-duration').value) || 7.0,
                creativity: (parseFloat(document.getElementById('creativity').value) || 10) / 10,
            };

            var submitBtn = form.querySelector('button[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.textContent = 'Starting...';

            fetch('/video/api/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.job_id) {
                    window.location.href = '/video/review/' + data.job_id;
                } else {
                    alert(data.error || 'Failed to start');
                    submitBtn.disabled = false;
                    submitBtn.textContent = 'Generate Concepts';
                }
            })
            .catch(function(err) {
                alert('Error: ' + err);
                submitBtn.disabled = false;
                submitBtn.textContent = 'Generate Concepts';
            });
        });
    }
}


// ---------------------------------------------------------------------------
// Video Review page
// ---------------------------------------------------------------------------

function initVideoReviewPage(jobId) {
    var progressBox = document.getElementById('progress-box');
    var progressText = document.getElementById('progress-text');
    var cardsContainer = document.getElementById('cards-container');
    var selectionBar = document.getElementById('selection-bar');
    var selectionCount = document.getElementById('selection-count');
    var produceBtn = document.getElementById('produce-selected-btn');

    var selectedIndices = new Set();

    pollVideoJob(jobId,
        function onProgress(msg) {
            if (progressText) progressText.textContent = msg;
        },
        function onDone(data) {
            if (progressBox) progressBox.style.display = 'none';
            renderVideoCards(data);
        },
        function onFailed(err) {
            if (progressBox) {
                progressBox.innerHTML = '<div class="error-box"><h2>Generation Failed</h2><p>' +
                    escapeHtml(err) + '</p><a href="/video/" class="btn btn-primary" style="margin-top:12px;">Try Again</a></div>';
            }
        }
    );

    function renderVideoCards(data) {
        if (!data.evaluated || !data.evaluated.length) {
            cardsContainer.innerHTML = '<div class="empty">No concepts were generated. Try a different topic.</div>';
            return;
        }

        var criteria = data.criteria || [];
        var html = '<h2>Review ' + data.evaluated.length + ' video meme concepts for "' + escapeHtml(data.topic || '') + '"</h2>';
        html += '<p style="color:#666;margin-bottom:20px;">Click cards to select concepts, then produce videos for your picks. Video production costs depend on provider settings and duration.</p>';

        data.evaluated.forEach(function(concept) {
            html += buildVideoCard(concept, criteria);
        });

        cardsContainer.innerHTML = html;

        // Click handlers
        cardsContainer.querySelectorAll('.meme-card').forEach(function(card) {
            card.addEventListener('click', function() {
                var idx = parseInt(card.dataset.index);
                if (selectedIndices.has(idx)) {
                    selectedIndices.delete(idx);
                    card.classList.remove('selected');
                } else {
                    selectedIndices.add(idx);
                    card.classList.add('selected');
                }
                updateSelectionBar();
            });
        });
    }

    function buildVideoCard(concept, criteria) {
        var html = '<div class="meme-card" data-index="' + concept.index + '">';
        html += '<div class="rank">' + concept.index + '</div>';
        html += '<div class="check">&#10003;</div>';
        html += '<div class="meme-content">';
        html += '<h3>' + escapeHtml(concept.title) + '</h3>';

        html += '<div class="meme-text"><strong>Hook:</strong> ' + escapeHtml(concept.hook) + '</div>';

        // Scenes
        (concept.scenes || []).forEach(function(scene) {
            html += '<div style="margin:8px 0;padding:8px;background:#f9f9f9;border-radius:4px;">';
            html += '<div style="font-weight:600;font-size:13px;color:#666;">Scene ' + scene.scene_number + ' (' + scene.duration_seconds + 's)</div>';
            html += '<div class="meme-text" style="margin-top:4px;"><strong>Visual:</strong> ' + escapeHtml(scene.visual_prompt) + '</div>';
            html += '<div class="meme-text"><strong>VO:</strong> ' + escapeHtml(scene.voiceover_text) + '</div>';
            if (scene.text_overlay) {
                html += '<div class="meme-text"><strong>Text:</strong> ' + escapeHtml(scene.text_overlay) + '</div>';
            }
            html += '</div>';
        });

        html += '<div class="meme-text"><strong>CTA:</strong> ' + escapeHtml(concept.cta_text) + '</div>';
        html += '<div class="meta"><span>Tone: ' + escapeHtml(concept.tone) + '</span><span>Audience: ' + escapeHtml(concept.target_audience) + '</span><span>' + concept.total_duration + 's</span></div>';

        // Score bars
        html += '<div style="margin-top:10px;">';
        criteria.forEach(function(crit) {
            var score = concept.scores[crit.name] || 0;
            var cls = score >= 7 ? 'high' : (score >= 4 ? 'mid' : 'low');
            html += '<div class="score-row">';
            html += '<span class="score-label">' + escapeHtml(crit.display_name) + '</span>';
            html += '<div class="score-bar-bg"><div class="score-bar ' + cls + '" style="width:' + (score * 10) + '%"></div></div>';
            html += '<span class="score-value">' + score + '</span>';
            html += '</div>';
        });
        var overallCls = concept.overall_score >= 7 ? 'high' : (concept.overall_score >= 4 ? 'mid' : 'low');
        html += '<div class="score-row" style="margin-top:4px;font-weight:600;">';
        html += '<span class="score-label">Overall</span>';
        html += '<div class="score-bar-bg"><div class="score-bar ' + overallCls + '" style="width:' + (concept.overall_score * 10) + '%"></div></div>';
        html += '<span class="score-value">' + concept.overall_score + '</span>';
        html += '</div>';
        html += '</div>';

        if (concept.evaluation_notes) {
            html += '<div class="eval-notes">' + escapeHtml(concept.evaluation_notes) + '</div>';
        }

        html += '</div></div>';
        return html;
    }

    function updateSelectionBar() {
        var count = selectedIndices.size;
        if (selectionCount) selectionCount.textContent = count + ' selected';
        if (selectionBar) {
            if (count > 0) selectionBar.classList.add('show');
            else selectionBar.classList.remove('show');
        }
    }

    if (produceBtn) {
        produceBtn.addEventListener('click', function() {
            if (selectedIndices.size === 0) return;
            produceBtn.disabled = true;
            produceBtn.textContent = 'Starting production...';

            fetch('/video/api/finalize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    job_id: jobId,
                    selected_indices: Array.from(selectedIndices),
                }),
            })
            .then(function(r) { return r.json(); })
            .then(function(data) {
                if (data.job_id) {
                    window.location.href = '/video/results/' + data.job_id;
                } else {
                    alert(data.error || 'Failed to start production');
                    produceBtn.disabled = false;
                    produceBtn.textContent = 'Produce Selected Video Memes';
                }
            })
            .catch(function(err) {
                alert('Error: ' + err);
                produceBtn.disabled = false;
                produceBtn.textContent = 'Produce Selected Video Memes';
            });
        });
    }
}


// ---------------------------------------------------------------------------
// Video Results page
// ---------------------------------------------------------------------------

function initVideoResultsPage(jobId) {
    var progressBox = document.getElementById('progress-box');
    var progressText = document.getElementById('progress-text');
    var resultsContainer = document.getElementById('results-container');

    // Poll more slowly — video production takes minutes
    pollVideoJob(jobId,
        function onProgress(msg) {
            if (progressText) progressText.textContent = msg;
        },
        function onDone(data) {
            if (progressBox) progressBox.style.display = 'none';
            renderVideoResults(data);
        },
        function onFailed(err) {
            if (progressBox) {
                progressBox.innerHTML = '<div class="error-box"><h2>Video Production Failed</h2><p>' +
                    escapeHtml(err) + '</p><a href="/video/" class="btn btn-primary" style="margin-top:12px;">Try Again</a></div>';
            }
        },
        5000  // Poll every 5s (video gen is slow)
    );

    function renderVideoResults(data) {
        if (!data.videos || !data.videos.length) {
            resultsContainer.innerHTML = '<div class="empty">No videos were produced.</div>';
            return;
        }

        var html = '<h2>' + data.videos.length + ' Video Memes Produced</h2>';

        if (data.cost_summary) {
            html += '<div class="counter">Total cost: $' + (data.cost_summary.total_spent || 0).toFixed(2) + '</div>';
        }

        html += '<div class="results-grid">';
        data.videos.forEach(function(video) {
            html += '<div class="result-card">';

            // Video player
            if (video.filename) {
                html += '<video controls style="width:100%;max-height:400px;border-radius:4px;background:#000;">';
                html += '<source src="/video/preview/' + encodeURIComponent(video.filename) + '" type="video/mp4">';
                html += 'Your browser does not support video playback.';
                html += '</video>';
            }

            html += '<div class="result-info">';
            html += '<h3>' + escapeHtml(video.title) + '</h3>';
            html += '<div class="meta">';
            html += '<span>Duration: ' + video.total_duration + 's</span>';
            html += '<span>Cost: $' + video.total_cost.toFixed(2) + '</span>';
            html += '</div>';
            html += '<div class="meme-text"><strong>Hook:</strong> ' + escapeHtml(video.hook) + '</div>';
            html += '<div class="meme-text"><strong>CTA:</strong> ' + escapeHtml(video.cta_text) + '</div>';

            // Download button
            if (video.filename) {
                html += '<div class="download-btns" style="margin-top:12px;">';
                html += '<a class="btn btn-download" href="/video/preview/' + encodeURIComponent(video.filename) + '" download>Download MP4</a>';
                html += '</div>';
            }

            html += '</div></div>';
        });
        html += '</div>';

        resultsContainer.innerHTML = html;
    }
}
